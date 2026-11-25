"""Middleware блокировки: забаненный пользователь не проходит ни в один обработчик.

Раньше бан проверялся только там, где о нём помнили: забаненный мог продолжать
создавать объявления и открывать сделки. Теперь проверка одна на все апдейты.
"""

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from database.repository import Repositories

logger = logging.getLogger(__name__)

BANNED_TEXT = "🚫 Ваш аккаунт заблокирован. Напишите администратору, если считаете это ошибкой."


class BanMiddleware(BaseMiddleware):
    """Не пускать забаненных: сообщение — ответ, callback — всплывающее окно."""

    def __init__(self, repos: Repositories):
        self.repos = repos

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        from_user = getattr(event, "from_user", None)
        if from_user is None:
            return await handler(event, data)

        user = await self.repos.users.get_by_telegram_id(from_user.id)
        if user and user.get("is_banned"):
            logger.info("Забаненный пользователь %s пытался действовать", from_user.id)
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer(BANNED_TEXT, show_alert=True)
                except Exception:  # noqa: BLE001 — устаревший callback
                    pass
            elif hasattr(event, "answer"):
                await event.answer(BANNED_TEXT)
            return None

        return await handler(event, data)
