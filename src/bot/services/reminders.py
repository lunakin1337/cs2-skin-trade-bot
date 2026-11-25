"""Напоминания по зависшим сделкам: фоновая задача, без отдельного демона."""

import asyncio
import logging

from aiogram import Bot

from bot.services import notifications
from database.repository import Repositories

logger = logging.getLogger(__name__)

CHECK_EVERY_SECONDS = 300


async def remind_stale_trades(
    bot: Bot, repos: Repositories, minutes: int = 15, web_app_url: str | None = None
) -> int:
    """Напомнить по сделкам, которые ждут подтверждения дольше `minutes`. Возвращает число."""
    stale = await repos.trades.stale_pending(minutes=minutes)
    sent = 0
    for trade in stale:
        await notifications.stale_trade(bot, repos, trade, web_app_url)
        await repos.trades.mark_reminded(trade["id"])
        sent += 1
    if sent:
        logger.info("Напоминания по зависшим сделкам: %s", sent)
    return sent


async def reminder_loop(
    bot: Bot, repos: Repositories, minutes: int = 15, web_app_url: str | None = None
) -> None:
    """Крутится рядом с поллингом; ошибки одного круга не останавливают задачу."""
    while True:
        await asyncio.sleep(CHECK_EVERY_SECONDS)
        try:
            await remind_stale_trades(bot, repos, minutes, web_app_url)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 — задача не должна падать
            logger.warning("Напоминания: круг не удался — %s", error)
