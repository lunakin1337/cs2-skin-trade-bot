# Инструкции: как запускать и обслуживать

Практическое руководство по проекту. Контекст и решения — в [PROGRESS.md](PROGRESS.md).

## 1. Что нужно на машине

- Python 3.11+
- Git
- Для работы бота: локальный прокси до Telegram Bot API (у нас Xray с VLESS-конфигом;
  Bot API с домашнего IP не открывается)
- Для Mini App: `cloudflared` (даёт HTTPS-адрес) — `C:\Program Files (x86)\cloudflared\cloudflared.exe`
- По желанию: `STEAM_API_KEY` с https://steamcommunity.com/dev/apikey (имя и аватар Steam)

## 2. Первая установка

```bash
cd C:\desktop\telegramBOT
pip install -e ".[dev]"
copy .env.example .env
```

В `.env` заполнить:

| Переменная | Обязательна | Что это |
|---|---|---|
| `BOT_TOKEN` | да | токен от @BotFather |
| `ADMIN_IDS` | нет | Telegram id админов через запятую (id 8851272459 админ всегда) |
| `DB_PATH` | нет | путь к SQLite, по умолчанию `data/bot.db` |
| `STEAM_API_KEY` | нет | имя/аватар Steam |
| `TELEGRAM_PROXY` | для дома | `socks5://127.0.0.1:10808` (локальный Xray) |
| `WEB_APP_URL` | для Mini App | HTTPS-адрес приложения (туннель или домен) |
| `WEB_ADMIN_TOKEN` | нет | доступ к странице `/stats` |

## 3. Запуск всего (обычный путь)

Двойной клик по **`start_all.bat`**. Скрипт делает по шагам:

1. ставит зависимости, если их нет;
2. поднимает Xray с конфигом `~/.capy/work/xray/config.json`;
3. поднимает веб-приложение на `http://localhost:8080`;
4. поднимает `cloudflared`, читает адрес туннеля и записывает его в `WEB_APP_URL`;
5. запускает бота.

Проверить, что всё живо:

```bash
curl http://127.0.0.1:8080/health          # {"status": "ok"}
netstat -ano | findstr :10808              # Xray слушает
type .env | findstr WEB_APP_URL            # адрес туннеля
```

В Telegram: бот → меню → «🌐 Приложение».

## 4. Запуск по частям

```bash
python -m src.bot.main        # только бот (нужен TELEGRAM_PROXY)
python -m src.web_app         # только веб-приложение и Mini App
make test                     # pytest
make lint                     # ruff
make migrate                  # применить миграции вручную
```

Скрипты `.bat`: `start_bot.bat` (Xray + бот), `run_all.bat` (веб + туннель + бот),
`run_bot.bat`, `run_webapp.bat`.

## 5. Telegram Bot API не работает напрямую

Симптом: в логах `ClientConnectorError`, таймауты, `Flood control exceeded`.

1. Убедиться, что Xray запущен: `netstat -ano | findstr :10808`.
2. В `.env` стоит `TELEGRAM_PROXY=socks5://127.0.0.1:10808`.
3. Проверить токен через прокси:

```bash
curl -s --socks5-hostname 127.0.0.1:10808 "https://api.telegram.org/bot<ТОКЕН>/getMe"
```

Должно вернуться `"ok":true`. Если приходит `429` — токен или IP под штрафом: подождать,
не дёргать API в цикле, проверить, что не запущено два поллера (см. ниже).

## 6. Обновить адрес Mini App

Адрес `trycloudflare` меняется при каждом перезапуске туннеля:

```bash
python scripts/refresh_webapp_url.py --log cloudflare.log
```

и перезапустить бота (он читает `WEB_APP_URL` при старте). Либо просто `start_all.bat`.

## 7. Диагностика частых проблем

| Симптом | Причина | Что делать |
|---|---|---|
| `TelegramConflictError: terminated by other getUpdates` | работают два поллера (локальный бот + GitHub Actions + зависший процесс) | найти и убить лишние: `Get-CimInstance Win32_Process -Filter "Name='python.exe'" \| ? { $_.CommandLine -like '*bot.main*' }`, отменить прогоны `Bot Live` |
| Mini App открывается, но кнопки не работают, «вечная загрузка» | синтаксическая ошибка в JS | `pytest tests/unit/test_mini_app.py` — тест парсит скрипт; смотреть консоль WebView |
| `/api/*` отвечает 401 | открыли не через Telegram или токен в `.env` не совпадает с ботом, из которого открыли | открывать кнопкой из бота; токен в `.env` = токен того бота |
| Пусто в инвентаре | инвентарь закрыт в Steam или не синхронизирован | Steam → Инвентарь → «Открытый», затем «Синхронизировать» |
| Скины есть, но их нет в списке оффера | торговый кулдаун (Steam отдаёт `tradable=1`, а срок в описании) | синхронизировать после окончания кулдауна |
| Не находится скин в каталоге | его ещё нет в базе | `python -m bot.services.skin_catalog --pages 50 --query "Asiimov"` |
| Статистика `/stats` отдаёт 403 | не задан или неверный `WEB_ADMIN_TOKEN` | задать в `.env` и открыть `/stats?token=...` |

## 8. Каталог скинов

Импорт (Steam придерживает запросы, поэтому медленно и с паузами):

```bash
python -m bot.services.skin_catalog --pages 250                 # популярное
python -m bot.services.skin_catalog --pages 60 --query "★"      # ножи и перчатки
python -m bot.services.skin_catalog --pages 40 --query "Sticker |"
```

Каталог также пополняется автоматически из инвентарей пользователей при синхронизации.

## 9. Деплой

**GitHub Actions (резерв):** workflow `Bot Live` — ручной запуск, держит поллинг ~5 ч 45 мин.
Не включать одновременно с локальным ботом: будет `Conflict`.

**VPS:** workflow `Deploy to VPS` (ручной). Нужны секреты репозитория:
`VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_PORT`, `BOT_TOKEN`, `ADMIN_IDS`,
`STEAM_API_KEY`, `WEB_ADMIN_TOKEN`. Собирается Docker-образ и запускается с `--env-file`.
Для Mini App на VPS нужен HTTPS: домен + сертификат либо `cloudflared` на сервере.

## 10. Тесты и качество

```bash
pytest -q                     # весь набор (113 тестов)
pytest tests/integration -q   # API и хендлеры
ruff check src tests scripts
```

Тесты используют временную SQLite, схема поднимается миграциями — как в проде.
Есть проверки: расчёт инвентаря и кулдаунов, разбор запросов, карточки, встречные
предложения и ссылки Steam, админские права, синтаксис JS в Mini App.

## 11. Безопасность

- Токен и ключи — только в `.env` (он в `.gitignore`) и в секретах GitHub. В код и
  `.env.example` секреты не попадают.
- Токен, который когда-то лежал в публичном репозитории, отозван; при утечке — сразу
  `@BotFather → Revoke current token`, затем обновить `.env` и секрет `BOT_TOKEN`.
- Админка: только Telegram id `8851272459` (плюс `ADMIN_IDS`). Проверка на сервере, не
  только в интерфейсе.
- Доступ к Mini App API — по подписи `initData`; без неё 401.

## 12. Резервные копии

- Копия базы на момент сборки 0.1: `data/bot-v0.1.db.bak`.
- Бэкап вручную: скопировать `data/bot.db` при остановленном боте (SQLite).
- Восстановление: положить файл обратно в `data/bot.db`, запустить бота — миграции
  доведут схему до актуальной.
