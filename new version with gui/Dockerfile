# CS2 Skin Trade Bot
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

# Сначала зависимости: слой кэшируется, пока не менялся код
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

RUN mkdir -p data

CMD ["python", "-m", "src.bot.main"]
