"""Middleware для логирования запросов."""

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Логирует все входящие апдейты."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Логируем сообщения
        if isinstance(event, Message):
            user = event.from_user
            text_preview = (event.text or event.caption or "")[:100]
            logger.info(
                "Message: user_id=%s username=%s text=%s",
                user.id if user else None,
                user.username if user else None,
                text_preview,
            )
        elif isinstance(event, CallbackQuery):
            user = event.from_user
            logger.info(
                "Callback: user_id=%s username=%s data=%s",
                user.id if user else None,
                user.username if user else None,
                event.data,
            )

        try:
            return await handler(event, data)
        except Exception as e:
            logger.exception("Error handling update: %s", e)
            raise