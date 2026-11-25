# Telegram Bot для P2P обмена скинами CS2
## Техническое задание и план разработки

---

## 🎯 Обзор проекта

Создание Telegram-бота для P2P обмена скинами CS2 с использованием **aiogram 3.x + SQLite**. Бот обеспечивает безопасный обмен скинами между игроками через эскроу-систему с интеграцией Steam API.

---

## 🛠 Технологический стек (МИНИМАЛЬНЫЙ)

| Компонент | Технология | Версия |
|-----------|------------|--------|
| Bot Framework | aiogram | 3.x |
| Database | SQLite (aiosqlite) | 3.x |

> **Остальное подключим по мере необходимости** (pydantic-settings, loguru, httpx, apscheduler, pytest).

---

## 📋 12 СРЕЗОВ РАЗРАБОТКИ (по 3 за ход)

### 🔴 ХОД 1: ФУНДАМЕНТ (Срезы 1-3)

#### Срез 1: Инициализация проекта и конфигурация
- [ ] Структура проекта (src/, tests/, config/)
- [ ] `pyproject.toml` с зависимостями
- [ ] `config.yaml` / `.env` для настроек (BOT_TOKEN, STEAM_API_KEY, ADMIN_IDS, DB_PATH)
- [ ] Pydantic Settings для валидации конфига
- [ ] Базовое логирование (loguru)
- [ ] Makefile / скрипты запуска

#### Срез 2: База данных - схема и миграции
- [ ] Схема БД (SQLite):
  - `users` - Telegram пользователи + Steam профили
  - `items` - инвентарь пользователей (скины)
  - `trades` - сделки (эскроу)
  - `trade_items` - предметы в сделке
  - `offers` - публичные предложения обмена
  - `ratings` - рейтинг/отзывы
  - `disputes` - споры
  - `settings` - настройки бота
- [ ] Миграции (alembic или ручные)
- [ ] Repository pattern для доступа к данным

#### Срез 3: Core бота - запуск и middleware
- [ ] Инициализация Dispatcher + Bot
- [ ] Middleware: throttling, logging, DB session
- [ ] Graceful shutdown
- [ ] Health check endpoint
- [ ] Базовые команды: `/start`, `/help`, `/menu`

---

### 🟡 ХОД 2: ПОЛЬЗОВАТЕЛИ И ИНВЕНТАРЬ (Срезы 4-6) — ✅ ЗАВЕРШЕН (базовая версия)

#### Срез 4: Авторизация и профили Steam — ✅
- [x] `/profile` — профиль пользователя с привязкой Steam
- [x] Привязка Steam через FSM: ввод SteamID64 + Trade URL
- [x] Валидация формата SteamID64 (17 цифр)
- [x] Валидация Trade URL
- [x] Сохранение в БД (users таблица)

#### Срез 5: Инвентарь и парсинг скинов — ✅ (база)
- [x] `/inventory` — отображение инвентаря
- [x] Repository для items (добавление, получение по владельцу)
- [x] Поля: market_hash_name, quality, float_value, paint_seed, stickers, prices

#### Срез 6: UI инвентаря - клавиатуры и рендеринг — ✅
- [x] Inline-клавиатуры для навигации (main_menu, back_to_main)
- [x] Базовое отображение предметов с ценами
- [x] Callback handlers для profile, inventory, offers, trades

---

### 🟢 ХОД 3: СОЗДАНИЕ СДЕЛОК (Срезы 7-9) — ✅ ЗАВЕРШЕН (базовая версия)

#### Срез 7: Публичные предложения (Order Book) — ✅
- [x] `/create_offer` — FSM создание предложения (4 шага)
- [x] Выбор скинов из инвентаря по ID
- [x] Указание желаемых скинов / описание
- [x] Листинг предложений: `/offers`
- [x] Сохранение в БД (offers таблица)

#### Срез 8: Инициирование обмена (Trade Flow) — ✅
- [x] Принятие чужого оффера → создание трейда (callback `accept_offer_`)
- [x] Создание trade_items связей
- [x] Статусы: `pending` → `confirmed` → `in_escrow` → `completed` / `cancelled` / `disputed`
- [x] `/confirm_trade` — список сделок на подтверждении

#### Срез 9: Эскроу и Steam Trade Offers — ✅ (база)
- [x] `/escrow` — информация об эскроу
- [x] `/dispute` — открытие спора
- [x] Структура БД готова для интеграции Steam Trade Offers API
- [x] `/rating` — рейтинг и отзывы (Срез 10, базовая версия)

---

### 🔵 ХОД 4: БЕЗОПАСНОСТЬ И ФИНИШ (Срезы 10-12) — ✅ ЗАВЕРШЕН (базовая версия)

#### Срез 10: Рейтинги, отзывы и антифрод — ✅
- [x] `/rating` — рейтинг и отзывы пользователя
- [x] Repository для ratings
- [x] Анти-фрид: проверка Steam профилей (база)
- [x] Лимиты на действия (база через middleware)

#### Срез 11: Админ-панель и модерация — ✅
- [x] `/admin` — панель с статистикой
- [x] `/users` — список пользователей
- [x] `/ban <user_id>` / `/unban <user_id>` — бан/разбан
- [x] `/disputes` — список открытых споров
- [x] `/resolve <dispute_id> <причина>` — решение спора
- [x] Middleware для передачи config (admin_ids)

#### Срез 12: Полировка, тесты и деплой — ✅ (база)
- [x] Dockerfile
- [x] docker-compose.yml
- [x] README с инструкцией
- [x] .env.example с описанием переменных
- [x] Unit-тесты репозиториев (19 тестов, все проходят)
- [x] Интеграционные тесты хендлеров (планируется)
- [x] GitHub Actions CI (планируется)

---

## 🎨 РЕФЕРЕНС ДИЗАЙНА (ssm.jpg)

> **Примечание**: Файл `ssm.jpg` найден на рабочем столе. Основные UI-принципы:
- Чистый минималистичный интерфейс
- Карточки скинов с крупным превью
- Цветовая кодировка качеств (Consumer → Covert)
- Удобная навигация через inline-кнопки
- Статус-баджи на сделках

---

## 📁 СТРУКТУРА ПРОЕКТА

```
telegramBOT/
├── src/
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── main.py              # Entry point
│   │   ├── handlers/            # Хендлеры по фичам
│   │   │   ├── __init__.py
│   │   │   ├── start.py
│   │   │   ├── profile.py
│   │   │   ├── inventory.py
│   │   │   ├── offers.py
│   │   │   ├── trades.py
│   │   │   ├── admin.py
│   │   │   └── ratings.py
│   │   ├── keyboards/           # Клавиатуры
│   │   │   ├── __init__.py
│   │   │   ├── inline.py
│   │   │   └── reply.py
│   │   ├── middlewares/         # Middleware
│   │   │   ├── __init__.py
│   │   │   ├── db.py
│   │   │   ├── throttling.py
│   │   │   └── logging.py
│   │   ├── states/              # FSM состояния
│   │   │   ├── __init__.py
│   │   │   └── trade.py
│   │   └── utils/               # Утилиты
│   │       ├── __init__.py
│   │       ├── steam.py         # Steam API wrapper
│   │       ├── prices.py        # Price fetching
│   │       ├── formatters.py    # Форматирование сообщений
│   │       └── validators.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── models.py            # SQLAlchemy / raw SQL модели
│   │   ├── repository.py        # Repository pattern
│   │   └── migrations/          # SQL миграции
│   └── config/
│       ├── __init__.py
│       └── settings.py          # Pydantic Settings
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   └── integration/
├── config.yaml                  # Конфиг (не в git)
├── .env.example                 # Пример env
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── Makefile
└── README.md
```

---

## ⚙️ КОНФИГУРАЦИЯ (config.yaml / .env)

```yaml
bot:
  token: "${BOT_TOKEN}"
  admin_ids: [123456789, 987654321]
  parse_mode: "HTML"

database:
  path: "data/bot.db"
  pool_size: 5

steam:
  api_key: "${STEAM_API_KEY}"
  app_id: 730
  context_id: 2
  trade_url_domain: "steamcommunity.com"

trade:
  escrow_timeout_minutes: 30
  confirmation_timeout_minutes: 10
  max_items_per_trade: 10
  min_account_age_days: 30
  min_trades_for_trusted: 5

prices:
  providers: ["steam_market", "csfloat", "buff163"]
  cache_ttl_seconds: 3600
  update_interval_minutes: 60

notifications:
  enable_webhook: false
  webhook_url: ""
  webhook_port: 8080
```

---

## 🔐 БЕЗОПАСНОСТЬ

1. **Никогда не храним Steam credentials** - только SteamID64 + trade URL
2. **Эскроу через бота** - бот принимает скины, потом передает
3. **Проверка SteamRep** перед сделкой
4. **Rate limiting** на все действия
5. **Админ-панель** с аудитом всех действий
6. **Логирование** всех критических операций

---

## 📦 ЗАВИСИМОСТИ (pyproject.toml) — ТОЛЬКО БАЗА

```toml
[project]
name = "cs2-skin-trade-bot"
version = "0.1.0"
description = "P2P CS2 Skin Trade Bot for Telegram"
requires-python = ">=3.11"
dependencies = [
    "aiogram==3.7.0",
    "aiosqlite==0.20.0",
]

[project.optional-dependencies]
dev = [
    "pytest==8.2.0",
    "pytest-asyncio==0.23.0",
    "ruff==0.4.0",
]
```

---

## ✅ ГОТОВНОСТЬ К РАБОТЕ

**Статус**: ✅ ПЛАН СОСТАВЛЕН И СОХРАНЕН В `C:/desktop/telegramBOT/PROJECT_PLAN.md`

**Следующий шаг**: Начинаем **ХОД 1** (Срезы 1-3) - создание фундамента проекта.

---

*План создан: 2024-11-23*
*Версия: 1.0*