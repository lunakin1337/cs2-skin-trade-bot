# CS2 Skin Trade Bot

P2P бот для обмена скинами CS2 на базе aiogram 3.x + SQLite.

## Стек
- aiogram 3.x
- SQLite (aiosqlite)

## Структура
```
src/
  config/       - конфигурация
  database/     - схема БД и репозитории
  bot/
    main.py     - точка входа
    handlers/   - хендеры команд
    keyboards/  - inline-клавиатуры
    middlewares/- middleware
    states/     - FSM состояния
    utils/      - утилиты форматирования
tests/          - тесты
data/           - файл SQLite БД
```

## Запуск

```bash
# Установка зависимостей
pip install -e .

# Настройка переменных окружения
cp .env.example .env
# отредактируйте .env, укажите BOT_TOKEN

# Запуск
python -m src.bot.main
```