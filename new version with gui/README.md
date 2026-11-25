# CS2 Skin Trade Bot

**Версия 0.2** — рабочая сборка с каталогом «на обмене», фильтрами, подбором обменов под инвентарь, спорами из интерфейса и Trade Protection в модели доверия.

P2P-обмен скинами CS2 в Telegram: привязка Steam-аккаунта и Trade URL, синхронизация
инвентаря с картинками и ценами, предложения обмена и сделки.

Подробности: [PROGRESS.md](PROGRESS.md) — память проекта и решения, [INSTRUCTIONS.md](INSTRUCTIONS.md) — как запускать и обслуживать.

## Стек

- aiogram 3.x
- SQLite (aiosqlite), миграции — свои, в `src/database/migrations`
- aiohttp — мини веб-приложение (витрина предложений и админ-сводка)

## Структура

```
src/
  config/            # конфигурация из .env
  database/
    repository.py    # Database + репозитории (users, items, offers, trades, ratings, disputes)
    migrations/      # схема БД; единственный источник правды
  bot/
    main.py          # точка входа (polling)
    handlers/        # роутеры: start, profile, inventory, offers, create_offer, trades, trade_flow, escrow, ratings, admin
    keyboards/       # inline-клавиатуры
    middlewares/     # logging, throttling, db
    states/          # FSM-состояния
    utils/           # steam, prices, validators, formatters, telegram
  web_app.py         # веб-приложение на aiohttp
tests/               # unit + integration
data/                # SQLite (в git не попадает)
```

Слои: хендлер → репозиторий → SQL. Внешние сервисы (Steam, цены) инкапсулированы
в `bot/utils`, поэтому хендлеры работают только с чистыми структурами и БД.

## Переменные окружения

| Переменная | Обязательна | Зачем |
|---|---|---|
| `BOT_TOKEN` | да | токен от @BotFather |
| `ADMIN_IDS` | нет | Telegram ID админов через запятую |
| `DB_PATH` | нет | путь к SQLite, по умолчанию `data/bot.db` |
| `STEAM_API_KEY` | нет | имя и аватар Steam (GetPlayerSummaries) |
| `WEB_APP_URL` | нет | HTTPS-адрес веб-приложения для кнопки Mini App |
| `WEB_ADMIN_TOKEN` | нет | доступ к `/admin` и `/stats`; без него разделы закрыты |
| `TELEGRAM_PROXY` | нет | прокси для Bot API, если прямой доступ заблокирован |

## Запуск

```bash
pip install -e ".[dev]"
cp .env.example .env        # заполните BOT_TOKEN
python -m src.bot.main      # бот
python -m src.web_app       # веб-приложение на :8080
```

Схему базы обновляет сам бот при старте (`run_migrations`), вручную — `make migrate`.

## Steam: что и откуда берётся

- **Профиль** (имя, аватар, ссылка) — Steam Web API `ISteamUser/GetPlayerSummaries`, нужен `STEAM_API_KEY`.
- **Trade URL** — пользователь вставляет ссылку `https://steamcommunity.com/tradeoffer/new/?partner=…&token=…`;
  из неё извлекаются `partner` и `token` и нормализованный URL сохраняется.
- **Инвентарь** — публичный эндпоинт Steam Community `/inventory/<steamid64>/730/2`: имена,
  редкость, износ, флаги tradable/marketable и хеш картинки. API-ключ не нужен, инвентарь
  должен быть открыт в настройках приватности Steam.
- **Картинки** — `https://community.cloudflare.steamstatic.com/economy/image/<icon_url>/360fx360f`.
- **Цены** — Steam Community Market (`priceoverview`) и CSFloat, кэш на час.

## Mini App

`/` отдаёт Telegram Mini App (`src/webapp/app.html`, SDK `telegram-web-app.js`):
инвентарь с картинками и ценами, кнопка синхронизации, предложения и профиль.

API работает только по подписанному `initData` — подпись проверяется HMAC-SHA256
от `BOT_TOKEN` (`bot/utils/telegram_auth.py`):

| Эндпоинт | Что отдаёт |
|---|---|
| `GET /api/me` | профиль, Steam-данные, счётчики инвентаря |
| `GET /api/inventory?page&size` | предметы с картинками и ценами, постранично |
| `POST /api/inventory/sync` | синхронизация со Steam (общая логика с ботом) |
| `GET /api/offers` | активные предложения |

Без валидного `initData` все `/api/*` отвечают 401. Для отладки вне Telegram
подпись можно передать в query: `/?initData=...`.

## Как проходит сделка

1. Покупатель принимает предложение в `/offers` — создаётся сделка со статусом `pending`.
2. Каждая сторона жмёт «Подтвердить»; после второго подтверждения статус `in_escrow`.
3. В `/trades` появляется кнопка «🔗 Обмен» — она открывает Steam Trade URL контрагента,
   поэтому обмен инициируется вручную, без хранения Steam-сессии бота.
4. Обе стороны жмут «📦 Получил» → статус `completed`, счётчики сделок растут,
   предложение закрывается.
5. Обе стороны ставят оценку 1–5 ⭐, средний рейтинг пересчитывается, контрагент получает уведомление.
6. До завершения любую сторону можно отменить — предложение вернётся в список активных.

## Где живёт бот

- **GitHub Actions (`Bot Live`)** — бесплатный вариант без сервера: job держит поллинг
  ~5 ч 45 мин, следующий запуск по расписанию каждые 6 часов подхватывает работу,
  база кэшируется между запусками. Нужны секреты `BOT_TOKEN` и `STEAM_API_KEY`
  (плюс опционально `ADMIN_IDS`, `WEB_APP_URL`). Для публичного репозитория минуты бесплатны.
- **VPS (`Deploy to VPS`)** — постоянный хостинг; запускается вручную после настройки
  секретов `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_PORT`, `BOT_TOKEN`,
  `ADMIN_IDS`, `STEAM_API_KEY`, `WEB_ADMIN_TOKEN`.
- **Локально** — `python -m src.bot.main`; если Bot API недоступен, укажите `TELEGRAM_PROXY`.

## Проверки

```bash
pytest        # 65 тестов
ruff check src tests
```
