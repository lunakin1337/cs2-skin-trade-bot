"""Веб-приложение: Telegram Mini App и служебные страницы.

Mini App отдаётся на `/`, данные — через JSON API (`web_api.py`), где каждый
запрос проверяет подпись initData по BOT_TOKEN.
"""

import html
import logging
import os
import time
import uuid
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import web

from bot.services.skin_query_llm import log_llm_status
from catalog_cache import CatalogCache
from config.settings import BotConfig, load_config, load_llm_config
from database import Repositories, init_database
from web_api import register_api_routes
from webapp_context import (
    BOT_KEY,
    CATALOG_CACHE_KEY,
    CONFIG_KEY,
    CONFIG_OVERRIDE_KEY,
    DB_PATH_OVERRIDE_KEY,
    REPOS_KEY,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

MINI_APP_PATH = Path(__file__).parent / "webapp" / "app.html"

BASE_STYLE = """
body { font-family: system-ui, sans-serif; max-width: 900px; margin: 32px auto; padding: 0 16px;
       color: #1c1c1e; }
h1 { font-size: 22px; }
nav a { display: inline-block; margin: 0 8px 8px 0; padding: 8px 14px; background: #2b6cb0;
        color: #fff; text-decoration: none; border-radius: 6px; font-size: 14px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #e2e2e2; }
.muted { color: #6b6b6f; font-size: 13px; }
"""


def _config(request: web.Request) -> BotConfig:
    return request.app[CONFIG_KEY]


def _repos(request: web.Request) -> Repositories:
    return request.app[REPOS_KEY]


def _authorized(request: web.Request) -> bool:
    token = _config(request).web_admin_token
    return bool(token) and request.query.get("token") == token


def _layout(title: str, body: str, token: str = "") -> str:
    auth = f"?token={html.escape(token)}" if token else ""
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{BASE_STYLE}</style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <nav>
    <a href="/">Приложение</a>
    <a href="/stats{auth}">Статистика</a>
  </nav>
  {body}
</body>
</html>"""


async def _render(request: web.Request, title: str, body: str) -> web.Response:
    token = request.query.get("token", "") if _authorized(request) else ""
    return web.Response(text=_layout(title, body, token), content_type="text/html")


async def mini_app(request: web.Request) -> web.Response:
    if not MINI_APP_PATH.exists():
        logger.error("Не найден файл Mini App: %s", MINI_APP_PATH)
        return web.Response(text="Mini App не собран", status=500)
    return web.FileResponse(MINI_APP_PATH)


async def health_check(request: web.Request) -> web.Response:
    """Живость сервиса: база отвечает, версия схемы и число миграций."""
    payload: dict[str, object] = {"status": "ok"}
    try:
        db = _repos(request).db
        cur = await db.execute("SELECT COUNT(*) AS cnt FROM migrations")
        row = await cur.fetchone()
        payload["migrations"] = row["cnt"] if row else 0
        cur = await db.execute("SELECT 1 AS ok")
        await cur.fetchone()
        payload["db"] = "ok"
    except Exception as error:  # noqa: BLE001 — health не должен падать, он сообщает
        logger.warning("Health: база не ответила — %s", error)
        payload["status"] = "degraded"
        payload["db"] = "error"
        return web.json_response(payload, status=503)
    return web.json_response(payload)


async def user_stats(request: web.Request) -> web.Response:
    if not _authorized(request):
        return web.Response(text="Доступ запрещён: нужен ?token=WEB_ADMIN_TOKEN", status=403)

    stats = {}
    for key, query in {
        "users": "SELECT COUNT(*) AS cnt FROM users",
        "items": "SELECT COUNT(*) AS cnt FROM items",
        "skins": "SELECT COUNT(*) AS cnt FROM skins",
        "offers": "SELECT COUNT(*) AS cnt FROM offers WHERE status = 'active'",
        "trades": "SELECT COUNT(*) AS cnt FROM trades",
        "open_disputes": "SELECT COUNT(*) AS cnt FROM disputes WHERE status = 'open'",
    }.items():
        cur = await _repos(request).db.execute(query)
        row = await cur.fetchone()
        stats[key] = row["cnt"] if row else 0

    body = "<table>" + "".join(
        f"<tr><td>{html.escape(name)}</td><td>{value}</td></tr>" for name, value in stats.items()
    ) + "</table>"
    return await _render(request, "Статистика", body)


async def on_startup(app: web.Application) -> None:
    config = app.get(CONFIG_OVERRIDE_KEY) or load_config()
    db_path = Path(app.get(DB_PATH_OVERRIDE_KEY) or config.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    app[CONFIG_KEY] = config
    app[REPOS_KEY] = Repositories(await init_database(str(db_path)))
    log_llm_status(load_llm_config())
    if BOT_KEY not in app:
        session = AiohttpSession(proxy=config.telegram_proxy) if config.telegram_proxy else None
        app[BOT_KEY] = Bot(token=config.token, session=session, default=DefaultBotProperties(parse_mode=config.parse_mode))
    logger.info("Веб-приложение готово, база: %s", db_path)


async def on_cleanup(app: web.Application) -> None:
    repos: Repositories | None = app.get(REPOS_KEY)
    if repos is not None:
        await repos.db.close()
    bot: Bot | None = app.get(BOT_KEY)
    if bot is not None:
        await bot.session.close()


# ---------- надёжность: ошибки и тайминги ----------


def _request_id(request: web.Request) -> str:
    """Идентификатор запроса: из заголовка или случайный, чтобы связать лог и ответ."""
    return request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]


@web.middleware
async def api_error_middleware(request: web.Request, handler):
    """Любое исключение в API — JSON с кодом и request_id, а не HTML-страница."""
    request_id = _request_id(request)
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:  # noqa: BLE001 — ловим всё, что не является штатным HTTP-ответом
        logger.exception(
            "API: необработанная ошибка %s %s (request_id=%s)", request.method, request.path, request_id
        )
        return web.json_response(
            {"error": "internal", "request_id": request_id},
            status=500,
            headers={"X-Request-Id": request_id},
        )


@web.middleware
async def api_timing_middleware(request: web.Request, handler):
    """Логировать метод, путь, статус и время ответа. Тело запроса и initData не пишем."""
    started = time.perf_counter()
    request_id = _request_id(request)
    try:
        response = await handler(request)
    except web.HTTPException as error:
        elapsed = (time.perf_counter() - started) * 1000
        logger.info(
            "%s %s -> %s за %.0f мс (request_id=%s)",
            request.method,
            request.path,
            error.status,
            elapsed,
            request_id,
        )
        raise
    response.headers.setdefault("X-Request-Id", request_id)
    elapsed = (time.perf_counter() - started) * 1000
    logger.info(
        "%s %s -> %s за %.0f мс (request_id=%s)",
        request.method,
        request.path,
        response.status,
        elapsed,
        request_id,
    )
    return response


def create_app(
    config: BotConfig | None = None,
    db_path: str | None = None,
) -> web.Application:
    # ограничение размера тела: JSON Mini App небольшой, 1 МБ с запасом
    app = web.Application(client_max_size=1024 * 1024)
    app[CONFIG_OVERRIDE_KEY] = config
    app[DB_PATH_OVERRIDE_KEY] = db_path
    app[CATALOG_CACHE_KEY] = CatalogCache()

    app.router.add_get("/", mini_app)
    app.router.add_get("/app", mini_app)
    app.router.add_get("/health", health_check)
    app.router.add_get("/stats", user_stats)
    register_api_routes(app)
    app.middlewares.append(api_error_middleware)
    app.middlewares.append(api_timing_middleware)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    web.run_app(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
