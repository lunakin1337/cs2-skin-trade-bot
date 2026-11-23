"""Хелперы работы с Telegram API."""

import logging
from typing import Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)

NOT_MODIFIED = "message is not modified"


async def edit_or_send(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """Отредактировать сообщение, а если нельзя (фото, устаревшее) — отправить новое."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as error:
        if NOT_MODIFIED in str(error):
            return
        await message.answer(text, reply_markup=reply_markup)


async def notify(callback: CallbackQuery, text: Optional[str] = None, alert: bool = False) -> None:
    """Ответить на callback и не падать, если он уже неактуален."""
    try:
        await callback.answer(text=text, show_alert=alert)
    except TelegramBadRequest:
        logger.debug("Не удалось ответить на callback %s", callback.id)
