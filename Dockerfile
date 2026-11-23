# Dockerfile для CS2 Skin Trade Bot
FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копирование файлов зависимостей
COPY pyproject.toml ./

# Установка Python зависимостей
RUN pip install --no-cache-dir -e .

# Копирование исходного кода
COPY src/ ./src/
COPY .env.example ./

# Создание директории для данных
RUN mkdir -p data

# Переменные окружения
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Запуск бота
CMD ["python", "-m", "src.bot.main"]