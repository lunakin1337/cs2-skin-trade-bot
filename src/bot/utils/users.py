"""Работа с пользователями Telegram."""

from aiogram.types import User

from database.repository import Repositories


async def ensure_user(repos: Repositories, from_user: User) -> dict:
    """Найти или создать пользователя бота по данным Telegram."""
    return await repos.users.create_or_update(
        telegram_id=from_user.id,
        username=from_user.username,
        first_name=from_user.first_name,
        last_name=from_user.last_name,
    )
