from typing import Annotated, List, Optional
from fastapi import FastAPI, HTTPException, Depends
import uvicorn
from pydantic import BaseModel, ConfigDict, field_serializer # Импортируем field_serializer
import requests
from datetime import datetime
from sqlalchemy import select, ForeignKey, Integer # Импортируем Integer на всякий случай
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
import os
from sqlalchemy.orm import selectinload # Импортируем для eager loading

# Инициализируем FastAPI приложение
app = FastAPI(
    title="Сервис Учета Заказ-Нарядов",
    description="API для управления заказ-нарядами и учета выполнения ремонтных работ."
)

# --- Configuration ---
REFERENCE_DATA_URL = os.getenv("REFERENCE_DATA_URL", "http://127.0.0.1:8000")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///local_repair_orders.db")

engine = create_async_engine(DATABASE_URL, echo=True)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# --- SQLAlchemy Base ---
class Base(DeclarativeBase):
    pass

# --- Database Models (ORM) ---
class RepairOrderModel(Base):
    __tablename__ = "repair_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_name: Mapped[str]
    client_phone: Mapped[str]
    car_make: Mapped[str]
    car_model: Mapped[str]
    car_plate: Mapped[str]
    employee_id: Mapped[int] # ORM - Mapped[int] ПРАВИЛЬНО
    status: Mapped[str]
    created_at: Mapped[datetime]
    description: Mapped[Optional[str]] = mapped_column(nullable=True)

    services: Mapped[List["RepairOrderServiceModel"]] = relationship(back_populates="repair_order")


class RepairOrderServiceModel(Base):
    __tablename__ = "repair_order_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column()
    repair_order_id: Mapped[int] = mapped_column(ForeignKey("repair_orders.id"))

    repair_order: Mapped[RepairOrderModel] = relationship(back_populates="services")


# --- Pydantic Schemas ---

class RepairOrderCreate(BaseModel):
    """Schema for creating a new Repair Order (для входящего запроса)."""
    # Разрешаем арбитражные типы и здесь, на всякий случай
    model_config = ConfigDict(arbitrary_types_allowed=True)

    client_name: str
    client_phone: str
    car_make: str
    car_model: str
    car_plate: str
    service_ids: List[int]
    employee_id: int # Pydantic - int ПРАВИЛЬНО
    description: Optional[str] = None


class RepairOrder(BaseModel): # Наследуется от BaseModel
    """Full schema for a Repair Order (для исходящего ответа)."""
    # Разрешаем Pydantic читать данные из ORM модели И разрешаем арбитражные типы
    model_config = ConfigDict(
        from_attributes=True,
        arbitrary_types_allowed=True # ЭТОТ ПАРАМЕТР ДОЛЖЕН БЫТЬ ЗДЕСЬ!
    )

    id: int
    client_name: str
    client_phone: str
    car_make: str
    car_model: str
    car_plate: str
    employee_id: int # Pydantic - int ПРАВИЛЬНО
    status: str
    created_at: datetime
    description: Optional[str] = None

    service_ids: List[int] = []

    @field_serializer('service_ids')
    def serialize_service_ids(self, services_relationship: List[RepairOrderServiceModel], _info):
        # Здесь может быть проблема, если services_relationship не является списком (например, из-за ленивой загрузки или ошибки).
        # Проверяем, является ли services_relationship итерируемым списком
        if isinstance(services_relationship, list):
             return [service_model.service_id for service_model in services_relationship]
        # Возвращаем пустой список или ошибку, если не список
        # logging.warning(f"services_relationship is not a list: {type(services_relationship)}") # Можно добавить логирование
        return []


class RepairOrderUpdate(BaseModel):
    """Schema for updating a Repair Order."""
    # Разрешаем арбитражные типы и здесь, на всякий случай
    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: Optional[str] = None
    description: Optional[str] = None


@app.post("/setup", summary="Настроить базу данных (создать таблицы)")
async def setup_database():
    """Создает новые таблицы на основе ORM моделей в подключенной БД."""
    async with engine.begin() as conn:
        # await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return {"message": "Настройка базы данных завершена"}

@app.post("/repair-orders",
         tags=["Repair Orders"],
         summary="Создать новый заказ-наряд")
async def create_repair_order(repair_order_data: RepairOrderCreate, session: SessionDep) -> RepairOrder:
    """Создает новый заказ-наряд. Требует валидные ID услуг и сотрудника из Сервиса Справочников."""
    # ... (код валидации и создания в БД остается тем же) ...
    try:
        for service_id in repair_order_data.service_ids:
            response = requests.get(f"{REFERENCE_DATA_URL}/services/{service_id}")
            response.raise_for_status()
        response = requests.get(f"{REFERENCE_DATA_URL}/employees/{repair_order_data.employee_id}")
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        if hasattr(e, 'response') and e.response is not None:
             raise HTTPException(status_code=e.response.status_code, detail=f"Ошибка Сервиса Справочников: {e.response.text}")
        else:
            raise HTTPException(status_code=500, detail=f"Ошибка связи с Сервисом Справочников: {e}")
    except HTTPException as e:
        raise e

    new_repair_order_model = RepairOrderModel(
        client_name=repair_order_data.client_name, client_phone=repair_order_data.client_phone,
        car_make=repair_order_data.car_make, car_model=repair_order_data.car_model,
        car_plate=repair_order_data.car_plate, employee_id=repair_order_data.employee_id,
        status="Новый", created_at=datetime.now(), description=repair_order_data.description,
    )
    session.add(new_repair_order_model)
    await session.commit()
    await session.refresh(new_repair_order_model)

    for service_id in repair_order_data.service_ids:
        repair_order_service_entry = RepairOrderServiceModel(
            service_id=service_id, repair_order_id=new_repair_order_model.id
        )
        session.add(repair_order_service_entry)

    await session.commit()
    # Для POST ответа, который должен содержать service_ids, нам нужно, чтобы отношение 'services' было загружено
    await session.refresh(new_repair_order_model, attribute_names=["services"])

    return new_repair_order_model # Pydantic должен справиться с arbitrary_types_allowed=True и сериализатором


@app.get("/repair-orders",
         tags=["Repair Orders"],
         summary="Получить список всех заказ-нарядов")
async def get_all_repair_orders(session: SessionDep) -> List[RepairOrder]:
    """Возвращает список всех заказ-нарядов."""
    # Используем selectinload для загрузки отношения 'services' вместе с основными объектами RepairOrderModel
    # Это необходимо, чтобы Pydantic сериализатор мог получить доступ к связанным объектам RepairOrderServiceModel
    result = await session.execute(select(RepairOrderModel).options(selectinload(RepairOrderModel.services)))
    repair_orders = result.scalars().all()
    # Pydantic будет использовать кастомный сериализатор для service_ids
    return repair_orders

@app.get("/repair-orders/{repair_order_id}",
         tags=["Repair Orders"],
         summary="Получить заказ-наряд по ID")
async def get_repair_order_by_id(repair_order_id: int, session: SessionDep) -> RepairOrder:
    """Возвращает заказ-наряд по его ID."""
    # Используем selectinload для загрузки отношения 'services'
    repair_order = await session.get(RepairOrderModel, repair_order_id, options=[selectinload(RepairOrderModel.services)])

    if not repair_order:
        raise HTTPException(status_code=404, detail="Заказ-наряд не найден")

    return repair_order


@app.put("/repair-orders/{repair_order_id}",
         tags=["Repair Orders"],
         summary="Обновить статус или описание заказ-наряда")
async def update_repair_order(repair_order_id: int, repair_order_update: RepairOrderUpdate, session: SessionDep) -> RepairOrder:
    """Обновляет статус или описание существующего заказ-наряда."""
    repair_order = await session.get(RepairOrderModel, repair_order_id, options=[selectinload(RepairOrderModel.services)])

    if not repair_order:
        raise HTTPException(status_code=404, detail="Заказ-наряд не найден")

    if repair_order_update.status is not None:
        repair_order.status = repair_order_update.status
    if repair_order_update.description is not None:
        repair_order.description = repair_order_update.description

    await session.commit()
    return repair_order


@app.delete("/repair-orders/{repair_order_id}",
            tags=["Repair Orders"],
            summary="Удалить заказ-наряд по ID (Требуется аутентификация)")
async def delete_repair_order(repair_order_id: int, session: SessionDep):
    """Удаляет заказ-наряд по его ID. В реальном приложении требуется аутентификация администратора."""
    repair_order = await session.get(RepairOrderModel, repair_order_id)
    if not repair_order:
        raise HTTPException(status_code=404, detail="Заказ-наряд не найден")

    await session.execute(select(RepairOrderServiceModel).where(RepairOrderServiceModel.repair_order_id == repair_order_id))

    await session.delete(repair_order)
    await session.commit()
    return {"success": True, "message": "Заказ-наряд успешно удален"}


if __name__ == "__main__":
    uvicorn.run("repair_order_service:app", host="127.0.0.1", port=8001, reload=True)