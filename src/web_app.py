"""Мини веб-приложение: Telegram Mini App и админ-сводка.

Mini App отдаётся на `/` и работает только с подписанным ``initData``:
эндпоинты ``/api/*`` проверяют HMAC-подпись от BOT_TOKEN.
Админ-страницы ``/admin`` и ``/stats`` защищены токеном WEB_ADMIN_TOKEN.
"""

import html
import logging
import os
from pathlib import Path

from aiohttp import web

from bot.services.inventory_sync import sync_inventory
from bot.utils.steam import TradeUrl
from bot.utils.telegram_auth import parse_init_data
from config.settings import BotConfig, load_config
from database import Repositories, init_database

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

MINI_APP_PATH = Path(__file__).parent / "webapp" / "app.html"

CONFIG_KEY: web.AppKey[BotConfig] = web.AppKey("config", BotConfig)
REPOS_KEY: web.AppKey[Repositories] = web.AppKey("repos", Repositories)
CONFIG_OVERRIDE_KEY: web.AppKey[object] = web.AppKey("config_override", object)
DB_PATH_OVERRIDE_KEY: web.AppKey[object] = web.AppKey("db_path_override", object)

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
    <a href="/offers{auth}">Предложения</a>
    <a href="/stats{auth}">Статистика</a>
    <a href="/admin{auth}">Админ</a>
  </nav>
  {body}
</body>
</html>"""


def _authorized(request: web.Request) -> bool:
    token = _config(request).web_admin_token
    return bool(token) and request.query.get("token") == token


async def _render(request: web.Request, title: str, body: str) -> web.Response:
    token = request.query.get("token", "") if _authorized(request) else ""
    return web.Response(text=_layout(title, body, token), content_type="text/html")


# ==================== Mini App ====================


async def mini_app(request: web.Request) -> web.Response:
    """HTML Telegram Mini App (данные подтягивает JS через /api)."""
    if not MINI_APP_PATH.exists():
        logger.error("Не найден файл Mini App: %s", MINI_APP_PATH)
        return web.Response(text="Mini App не собран", status=500)
    return web.FileResponse(MINI_APP_PATH)


def _init_data(request: web.Request) -> str:
    return request.headers.get("X-Telegram-Init-Data") or request.query.get("initData") or ""


async def _api_user(request: web.Request) -> dict | None:
    """Пользователь по подписи initData или None, если подпись неверна."""
    parsed = parse_init_data(_init_data(request), _config(request).token)
    if not parsed or not parsed.get("user"):
        return None

    telegram_user = parsed["user"]
    telegram_id = telegram_user.get("id")
    if not telegram_id:
        return None

    return await _repos(request).users.create_or_update(
        telegram_id=int(telegram_id),
        username=telegram_user.get("username"),
        first_name=telegram_user.get("first_name"),
        last_name=telegram_user.get("last_name"),
    )


def _unauthorized() -> web.Response:
    return web.json_response({"error": "unauthorized"}, status=401)


async def api_me(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    repos = _repos(request)
    trade_url = None
    if user.get("steam_trade_partner") and user.get("steam_trade_token"):
        trade_url = TradeUrl(
            partner=str(user["steam_trade_partner"]),
            token=str(user["steam_trade_token"]),
        ).masked

    return web.json_response(
        {
            "telegram_id": user["telegram_id"],
            "username": user.get("username"),
            "first_name": user.get("first_name"),
            "rating": user.get("rating") or 0,
            "trades_count": user.get("trades_count") or 0,
            "steam": {
                "linked": bool(user.get("is_steam_linked")),
                "persona": user.get("steam_persona"),
                "avatar": user.get("steam_avatar_url"),
                "profile_url": user.get("steam_profile_url"),
                "trade_url": trade_url,
            },
            "inventory": {
                "count": await repos.items.count_by_owner(user["id"]),
                "tradable": await repos.items.count_by_owner(user["id"], tradable_only=True),
                "value": round(await repos.items.sum_price(user["id"]), 2),
                "synced_at": user.get("inventory_synced_at"),
            },
        }
    )


async def api_inventory(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    try:
        page = max(0, int(request.query.get("page", "0")))
    except ValueError:
        page = 0
    try:
        size = min(50, max(1, int(request.query.get("size", "20"))))
    except ValueError:
        size = 20

    repos = _repos(request)
    total = await repos.items.count_by_owner(user["id"])
    items = await repos.items.get_by_owner(user["id"], limit=size, offset=page * size)

    return web.json_response(
        {
            "total": total,
            "page": page,
            "size": size,
            "pages": max(1, -(-total // size)),
            "items": [
                {
                    "id": item["id"],
                    "name": item.get("market_hash_name") or item.get("item_name") or "—",
                    "image": item.get("image_url"),
                    "price": item.get("price_steam"),
                    "tradable": bool(item.get("is_tradable")),
                    "rarity": item.get("rarity"),
                    "exterior": item.get("exterior"),
                }
                for item in items
            ],
        }
    )


async def api_inventory_sync(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    report = await sync_inventory(_repos(request), user, _config(request))
    status = 200 if report.get("ok") else 400
    return web.json_response(report, status=status)


async def api_offers(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    offers = await _repos(request).offers.get_active(limit=30)
    return web.json_response(
        {
            "items": [
                {
                    "id": offer["id"],
                    "title": offer["title"],
                    "summary": offer.get("description"),
                    "seller": offer.get("username"),
                    "rating": offer.get("rating") or 0,
                    "wants": offer.get("items_wanted"),
                    "own": offer["creator_id"] == user["id"],
                }
                for offer in offers
            ]
        }
    )


async def health_check(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


# ==================== Админ-страницы ====================


async def offers_list(request: web.Request) -> web.Response:
    offers = await _repos(request).offers.get_active(limit=50)

    if not offers:
        return await _render(request, "Предложения", "<p>Активных предложений нет.</p>")

    rows = "".join(
        "<tr>"
        f"<td>#{offer['id']}</td>"
        f"<td>{html.escape(offer['title'])}</td>"
        f"<td>@{html.escape(offer.get('username') or '—')}</td>"
        f"<td>{offer.get('rating') or 0:.1f} ⭐</td>"
        f"<td>{html.escape(offer.get('items_wanted') or '—')}</td>"
        "</tr>"
        for offer in offers
    )
    return await _render(
        request,
        "Предложения",
        "<table><thead><tr><th>ID</th><th>Название</th><th>Продавец</th>"
        f"<th>Рейтинг</th><th>Хочет</th></tr></thead><tbody>{rows}</tbody></table>",
    )


async def admin_panel(request: web.Request) -> web.Response:
    if not _authorized(request):
        return web.Response(text="Доступ запрещён: нужен ?token=WEB_ADMIN_TOKEN", status=403)

    cur = await _repos(request).db.execute(
        """
        SELECT telegram_id, username, first_name, is_steam_linked, is_banned, rating, trades_count
        FROM users ORDER BY id DESC LIMIT 100
        """
    )
    users = await cur.fetchall()

    rows = "".join(
        "<tr>"
        f"<td>{user['telegram_id']}</td>"
        f"<td>@{html.escape(user['username'] or '—')}</td>"
        f"<td>{html.escape(user['first_name'] or '—')}</td>"
        f"<td>{'✅' if user['is_steam_linked'] else '❌'}</td>"
        f"<td>{'🔴' if user['is_banned'] else '🟢'}</td>"
        f"<td>{user['rating']:.1f}</td>"
        f"<td>{user['trades_count']}</td>"
        "</tr>"
        for user in users
    )

    return await _render(
        request,
        "Пользователи",
        "<table><thead><tr><th>Telegram ID</th><th>Username</th><th>Имя</th>"
        f"<th>Steam</th><th>Статус</th><th>Рейтинг</th><th>Сделки</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>",
    )


async def user_stats(request: web.Request) -> web.Response:
    if not _authorized(request):
        return web.Response(text="Доступ запрещён: нужен ?token=WEB_ADMIN_TOKEN", status=403)

    stats = {}
    for key, query in {
        "users": "SELECT COUNT(*) AS cnt FROM users",
        "items": "SELECT COUNT(*) AS cnt FROM items",
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


# ==================== Приложение ====================


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
    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/inventory", api_inventory)
    app.router.add_post("/api/inventory/sync", api_inventory_sync)
    app.router.add_get("/api/offers", api_offers)
    app.router.add_get("/health", health_check)
    app.router.add_get("/offers", offers_list)
    app.router.add_get("/admin", admin_panel)
    app.router.add_get("/stats", user_stats)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    web.run_app(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
