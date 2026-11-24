"""Веб-приложение: Telegram Mini App и служебные страницы.

Mini App отдаётся на `/`, данные — через JSON API (`web_api.py`), где каждый
запрос проверяет подпись initData по BOT_TOKEN.
"""

import html
import logging
import os
from pathlib import Path

from aiohttp import web

from config.settings import BotConfig, load_config
from database import Repositories, init_database
from web_api import register_api_routes
from webapp_context import CONFIG_KEY, CONFIG_OVERRIDE_KEY, DB_PATH_OVERRIDE_KEY, REPOS_KEY

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
    return web.json_response({"status": "ok"})


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
    logger.info("Веб-приложение готово, база: %s", db_path)


async def on_cleanup(app: web.Application) -> None:
    repos: Repositories | None = app.get(REPOS_KEY)
    if repos is not None:
        await repos.db.close()


def create_app(
    config: BotConfig | None = None,
    db_path: str | None = None,
) -> web.Application:
    app = web.Application()
    app[CONFIG_OVERRIDE_KEY] = config
    app[DB_PATH_OVERRIDE_KEY] = db_path

    app.router.add_get("/", mini_app)
    app.router.add_get("/app", mini_app)
    app.router.add_get("/health", health_check)
    app.router.add_get("/stats", user_stats)
    register_api_routes(app)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    web.run_app(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
