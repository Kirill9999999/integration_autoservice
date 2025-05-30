# Используем легковесный образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app


# Используем --no-cache-dir для экономии места
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь остальной код проекта в рабочую директорию
COPY . .


# Оставляем ENTRYPOINT пустым или указываем что-то базовое
ENTRYPOINT []
CMD []