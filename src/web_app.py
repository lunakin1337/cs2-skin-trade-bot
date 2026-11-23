"""Мини web-приложение для бота CS2 skin trade."""

import asyncio
import logging
import os
from typing import List, Dict, Any

from aiohttp import web

from config.settings import load_config
from database import Database
from database.models import SCHEMA
from database.repository import Repositories

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = web.Application()
repos: Repositories = None


async def init_db() -> None:
    """Инициализация базы данных."""
    global repos
    config = load_config()
    db = Database(db_path=config.db_path)
    await db.connect()
    await db.init_schema(SCHEMA)
    repos = Repositories(db)
    logger.info("Web приложение: база данных инициализирована")


# ==================== Маршруты ====================

async def index(request: web.Request) -> web.Response:
    """Главная страница."""
    return web.Response(
        text="""<!DOCTYPE html>
<html>
<head><title>CS2 Skin Trade Bot</title></head>
<body>
    <h1>CS2 Skin Trade Bot</h1>
    <p>Минимальное веб-приложение для просмотра</p>
    <ul>
        <li><a href="/admin">Панель админа</a></li>
        <li><a href="/offers">Предложения</a></li>
    </ul>
</body>
</html>""",
        content_type="text/html"
    )


async def admin_panel(request: web.Request) -> web.Response:
    """Панель администратора."""
    users = await repos.users.get_all()
    offers = await repos.offers.get_all()
    
    html = """<!DOCTYPE html>
<html>
<head><title>Админ панель</title></head>
<body>
    <h1>Админ панель</h1>
    
    <h2>Пользователи</h2>
    <table border="1">
        <tr><th>ID</th><th>Telegram ID</th><th>Username</th><th>Steam ID</th><th>Бан</th></tr>"""
    
    for user in users:
        ban_status = "🔴 Бан" if user.get("is_banned") else "🟢 Нет"
        html += f"""
        <tr>
            <td>{user['id']}</td>
            <td>{user['telegram_id']}</td>
            <td>@{user.get('username', '-')}</td>
            <td>{user.get('steam_id', '-')}</td>
            <td>{ban_status}</td>
        </tr>"""
    
    html += """
    </table>
    
    <h2>Предложения</h2>
    <table border="1">
        <tr><th>ID</th><th>Заголовок</th><th>Автор</th><th>Статус</th></tr>"""
    
    for offer in offers:
        author = await repos.users.get_by_id(offer["author_id"])
        html += f"""
        <tr>
            <td>{offer['id']}</td>
            <td>{offer['title']}</td>
            <td>@{author.get('username', '-') if author else '-'}</td>
            <td>{offer['status']}</td>
        </tr>"""
    
    html += """
    </table>
    
    <p><a href="/">Назад</a></p>
</body>
</html>"""
    
    return web.Response(text=html, content_type="text/html")


async def offers_list(request: web.Request) -> web.Response:
    """Список публичных предложений."""
    offers = await repos.offers.get_active()
    
    html = """<!DOCTYPE html>
<html>
<head><title>Предложения</title></head>
<body>
    <h1>Предложения обмена</h1>"""
    
    if not offers:
        html += "<p>Нет активных предложений.</p>"
    else:
        html += "<table border='1'><tr><th>ID</th><th>Заголовок</th><th>Автор</th><th>Статус</th></tr>"
        for offer in offers:
            author = await repos.users.get_by_id(offer["author_id"])
            html += f"""
            <tr>
                <td>{offer['id']}</td>
                <td>{offer['title']}</td>
                <td>@{author.get('username', '-') if author else '-'}</td>
                <td>{offer['status']}</td>
            </tr>"""
        html += "</table>"
    
    html += """
    <p><a href="/">Назад</a></p>
</body>
</html>"""
    
    return web.Response(text=html, content_type="text/html")


async def user_stats(request: web.Request) -> web.Response:
    """Статистика пользователей."""
    users = await repos.users.get_all()
    
    total_users = len(users)
    active_users = len([u for u in users if not u.get("is_banned")])
    linked_users = len([u for u in users if u.get("is_steam_linked")])
    
    html = f"""<!DOCTYPE html>
<html>
<head><title>Статистика</title></head>
<body>
    <h1>Статистика</h1>
    <ul>
        <li>Всего пользователей: {total_users}</li>
        <li>Активных: {active_users}</li>
        <li>С привязанным Steam: {linked_users}</li>
    </ul>
    <p><a href="/">Назад</a></p>
</body>
</html>"""
    
    return web.Response(text=html, content_type="text/html")


async def health_check(request: web.Request) -> web.Response:
    """Health check endpoint для render.com."""
    return web.json_response({"status": "ok"})


# ==================== Регистрация маршрутов ====================

app.router.add_get("/", index)
app.router.add_get("/admin", admin_panel)
app.router.add_get("/offers", offers_list)
app.router.add_get("/stats", user_stats)
app.router.add_get("/health", health_check)


# ==================== Запуск ====================

async def startup(app: web.Application) -> None:
    """Startup hook для aiohttp."""
    await init_db()


async def cleanup(app: web.Application) -> None:
    """Cleanup hook."""
    if repos and repos.db:
        await repos.db.close()


app.on_startup.append(startup)
app.on_cleanup.append(cleanup)


def main():
    """Запуск веб-приложения."""
    port = int(os.getenv("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()