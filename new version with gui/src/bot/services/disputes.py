"""Споры по сделкам: открытие участником и уведомления админу и второй стороне."""

import html
import logging
import sqlite3

from aiogram import Bot

from database.repository import Repositories

logger = logging.getLogger(__name__)

SUPER_ADMIN_ID = 8851272459
DISPUTE_STATUSES = {"confirmed", "in_escrow"}
REASON_MIN = 5
REASON_MAX = 1000


class DisputeError(Exception):
    """Спор открыть нельзя; текст — для пользователя."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


async def open_dispute(repos: Repositories, trade_id: int, user_id: int, reason: str) -> tuple[int, dict]:
    """Проверить права и открыть спор. Возвращает id спора и сделку."""
    trade = await repos.trades.get_by_id(trade_id)
    if not trade:
        raise DisputeError("Сделка не найдена", 404)
    if user_id not in {trade["buyer_id"], trade["seller_id"]}:
        raise DisputeError("Это не ваша сделка", 403)
    if trade["status"] not in DISPUTE_STATUSES:
        raise DisputeError("Спор можно открыть только по подтверждённой сделке в процессе обмена")

    reason = (reason or "").strip()
    if len(reason) < REASON_MIN:
        raise DisputeError("Опишите причину спора подробнее")
    reason = reason[:REASON_MAX]

    if await repos.disputes.get_open_by_trade(trade_id):
        raise DisputeError("По этой сделке уже открыт спор", 409)
    try:
        dispute_id = await repos.disputes.create(trade_id, user_id, reason)
    except sqlite3.IntegrityError as error:
        raise DisputeError("По этой сделке уже открыт спор", 409) from error
    return dispute_id, trade


async def notify_dispute(
    bot: Bot,
    repos: Repositories,
    trade: dict,
    dispute_id: int,
    opener_id: int,
    reason: str,
    admin_ids: list[int] | None = None,
) -> None:
    """Сообщить админам и второй стороне. Ошибки доставки не роняют запрос."""
    opener_is_buyer = trade["buyer_id"] == opener_id
    opener_name = trade["buyer_username"] if opener_is_buyer else trade["seller_username"]
    counterpart = await repos.users.get_by_id(trade["seller_id"] if opener_is_buyer else trade["buyer_id"])
    safe_reason = html.escape(reason.strip()[:REASON_MAX])

    admin_text = (
        f"⚖️ <b>Новый спор #{dispute_id}</b> по сделке #{trade['id']}\n"
        f"Открыл: @{html.escape(opener_name or '—')}\n"
        f"Причина: {safe_reason}\n\n"
        f"Решить: /resolve {dispute_id} &lt;решение&gt;"
    )
    counterpart_text = (
        f"⚠️ По сделке #{trade['id']} открыт спор.\n"
        f"Причина: {safe_reason}\n\n"
        "Администратор свяжется с обеими сторонами."
    )

    recipients = [(telegram_id, admin_text) for telegram_id in dict.fromkeys([SUPER_ADMIN_ID, *(admin_ids or [])])]
    if counterpart and counterpart.get("telegram_id"):
        recipients.append((counterpart["telegram_id"], counterpart_text))

    for telegram_id, text in recipients:
        try:
            await bot.send_message(telegram_id, text, parse_mode="HTML")
        except Exception as error:  # получатель мог заблокировать бота или Bot API недоступен
            logger.warning("Не удалось уведомить %s о споре #%s: %s", telegram_id, dispute_id, error)
