from typing import Annotated, List
from fastapi import FastAPI, HTTPException, Depends
import uvicorn
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
import os # Импортируем библиотеку os

# Инициализируем FastAPI приложение для этого сервиса с русскими названиями
app = FastAPI(
    title="Сервис Справочников", # Русское название сервиса
    description="API для управления справочными данными об услугах и сотрудниках автосервиса." # Русское описание сервиса
)

# --- Database Configuration ---
# Строка подключения к БД теперь полностью берется из переменной окружения DATABASE_URL
# Пример для PostgreSQL: postgresql+asyncpg://user:password@host:port/database
# Дефолтное значение для локального запуска с SQLite (если aiosqlite установлен)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///local_reference_data.db")

# Создаем асинхронный движок базы данных
engine = create_async_engine(DATABASE_URL, echo=True)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

# Dependency Injection для получения асинхронной сессии базы данных
async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# --- SQLAlchemy Base for declarative models ---
class Base(DeclarativeBase):
    pass

# --- Database Models (ORM) - Модели остаются такими же, как для SQLite ---
class ServiceModel(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    price: Mapped[float]
    duration_minutes: Mapped[int]

class EmployeeModel(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str]
    position: Mapped[str]

# --- Pydantic Schemas (остаются без изменений) ---
class ServiceCreate(BaseModel):
    name: str
    price: float
    duration_minutes: int

class Service(ServiceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int

class EmployeeCreate(BaseModel):
    full_name: str
    position: str

class Employee(EmployeeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int

# --- API Endpoints (остаются без изменений, кроме /setup) ---

@app.post("/setup", summary="Настроить базу данных (создать таблицы)")
async def setup_database():
    """Создает новые таблицы на основе ORM моделей в подключенной БД."""
    async with engine.begin() as conn:
        # Внимание: drop_all удалит все данные! Для production используйте миграции (Alembic)
        # await conn.run_sync(Base.metadata.drop_all) # Закомментировано, чтобы не удалять данные при каждом setup
        await conn.run_sync(Base.metadata.create_all)
    return {"message": "Настройка базы данных завершена"}

# ... (Остальные эндпоинты /services, /employees, DELETE - код остается тем же) ...

@app.post("/services", # Английский путь
         tags=["Services"], # Английский тег
         summary="Добавить новую услугу (Только для администраторов)")
async def create_service(new_service: ServiceCreate, session: SessionDep) -> Service:
    """Добавляет новую услугу в справочник. В реальном приложении требуется аутентификация администратора."""
    service = ServiceModel(
        name=new_service.name,
        price=new_service.price,
        duration_minutes=new_service.duration_minutes
    )
    session.add(service)
    await session.commit()
    await session.refresh(service)
    return service

@app.get("/services",
         tags=["Services"],
         summary="Получить список всех услуг")
async def get_all_services(session: SessionDep) -> List[Service]:
    """Возвращает список всех услуг автосервиса."""
    result = await session.execute(select(ServiceModel))
    services = result.scalars().all()
    return services

@app.get("/services/{service_id}",
         tags=["Services"],
         summary="Получить информацию об услуге по ID")
async def get_service_by_id(service_id: int, session: SessionDep) -> Service:
    """Возвращает информацию о конкретной услуге по ее ID."""
    service = await session.get(ServiceModel, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Услуга не найдена")
    return service

@app.post("/employees",
          tags=["Employees"],
          summary="Добавить нового сотрудника (Только для администраторов)")
async def create_employee(new_employee: EmployeeCreate, session: SessionDep) -> Employee:
    """Добавляет нового сотрудника в справочник. В реальном приложении требуется аутентификация администратора."""
    employee = EmployeeModel(
        full_name=new_employee.full_name,
        position=new_employee.position
    )
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    return employee

@app.get("/employees",
         tags=["Employees"],
         summary="Получить список всех сотрудников")
async def get_all_employees(session: SessionDep) -> List[Employee]:
    """Возвращает список всех сотрудников автосервиса."""
    result = await session.execute(select(EmployeeModel))
    employees = result.scalars().all()
    return employees

@app.get("/employees/{employee_id}",
         tags=["Employees"],
         summary="Получить информацию о сотруднике по ID")
async def get_employee_by_id(employee_id: int, session: SessionDep) -> Employee:
    """Возвращает информацию о сотруднике по его ID."""
    employee = await session.get(EmployeeModel, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    return employee

@app.delete("/services/{service_id}",
            tags=["Services"],
            summary="Удалить услугу по ID (Только для администраторов)")
async def delete_service(service_id: int, session: SessionDep):
    """Удаляет услугу из справочника по ее ID. В реальном приложении требуется аутентификация администратора."""
    service = await session.get(ServiceModel, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Услуга не найдена")
    await session.delete(service)
    await session.commit()
    return {"success": True, "message": "Услуга успешно удалена"}

@app.delete("/employees/{employee_id}",
            tags=["Employees"],
            summary="Удалить сотрудника по ID (Только для администраторов)")
async def delete_employee(employee_id: int, session: SessionDep):
    """Удаляет сотрудника из справочника по его ID. В реальном приложении требуется аутентификация администратора."""
    employee = await session.get(EmployeeModel, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    await session.delete(employee)
    await session.commit()
    return {"success": True, "message": "Сотрудник успешно удален"}


if __name__ == "__main__":
    # Локальный запуск с дефолтной SQLite БД, если не задана переменная окружения DATABASE_URL
    uvicorn.run("reference_data_service:app", host="127.0.0.1", port=8000, reload=True)