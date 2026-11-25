"""Уведомления по сделкам: вторая сторона узнаёт о шаге сразу, а не при открытии приложения.

Раньше бот молчал: предложение обмена приходило «в никуда», и сделка стояла, пока
человек сам не откроет Mini App. Здесь все события сделки, которые касаются контрагента.
"""

import logging
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from database.repository import Repositories

logger = logging.getLogger(__name__)

TRADE_HINT = "Все сделки — в Mini App, кнопка ниже."


def _open_app(web_app_url: Optional[str]) -> Optional[InlineKeyboardMarkup]:
    if not web_app_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть сделки", web_app=WebAppInfo(url=web_app_url))]
        ]
    )


async def _send(
    bot: Bot, telegram_id: Optional[int], text: str, web_app_url: Optional[str] = None
) -> bool:
    """Отправить сообщение, не падая на «бот заблокирован» или «не начинал диалог»."""
    if not telegram_id:
        return False
    try:
        await bot.send_message(telegram_id, text, reply_markup=_open_app(web_app_url))
        return True
    except Exception as error:  # noqa: BLE001 — уведомление не должно ломать сделку
        logger.debug("Уведомление %s не доставлено: %s", telegram_id, error)
        return False


async def _telegram_id(repos: Repositories, user_id: Optional[int]) -> Optional[int]:
    if not user_id:
        return None
    user = await repos.users.get_by_id(user_id)
    return user.get("telegram_id") if user else None


async def _name(repos: Repositories, user_id: Optional[int]) -> str:
    if not user_id:
        return "контрагент"
    user = await repos.users.get_by_id(user_id)
    if not user:
        return "контрагент"
    if user.get("username"):
        return f"@{user['username']}"
    return user.get("first_name") or "контрагент"


async def _title(repos: Repositories, trade: Dict[str, Any]) -> str:
    offer_id = trade.get("offer_id")
    if not offer_id:
        return "Обмен"
    offer = await repos.offers.get_by_id(offer_id)
    return offer.get("title") if offer else "Обмен"


async def new_trade(
    bot: Bot, repos: Repositories, trade: Dict[str, Any], web_app_url: Optional[str] = None
) -> None:
    """Кто-то предложил обмен по объявлению — сообщить автору объявления."""
    seller_tg = await _telegram_id(repos, trade.get("seller_id"))
    buyer_name = await _name(repos, trade.get("buyer_id"))
    title = await _title(repos, trade)
    await _send(
        bot,
        seller_tg,
        f"🤝 <b>Новое предложение обмена #{trade['id']}</b>\n\n"
        f"{buyer_name} предлагает обмен: <b>{title}</b>\n\n"
        "Подтвердите или откажите — сделка ждёт вас.",
        web_app_url,
    )


async def both_confirmed(
    bot: Bot, repos: Repositories, trade: Dict[str, Any], web_app_url: Optional[str] = None
) -> None:
    """Обе стороны подтвердили: пора в Steam, ссылка уже в карточке сделки."""
    title = await _title(repos, trade)
    for user_id, other_id in (
        (trade.get("buyer_id"), trade.get("seller_id")),
        (trade.get("seller_id"), trade.get("buyer_id")),
    ):
        await _send(
            bot,
            await _telegram_id(repos, user_id),
            f"🔗 <b>Обмен #{trade['id']} согласован</b>\n\n"
            f"{await _name(repos, other_id)} подтвердил(а): <b>{title}</b>\n\n"
            "Откройте сделку и нажмите «Steam Trade» — предметы уже стоят в окне обмена.",
            web_app_url,
        )


async def side_received(
    bot: Bot,
    repos: Repositories,
    trade: Dict[str, Any],
    from_user_id: Optional[int],
    web_app_url: Optional[str] = None,
) -> None:
    """Одна сторона отметила получение — второй нужно сделать то же."""
    other_id = (
        trade.get("seller_id") if from_user_id == trade.get("buyer_id") else trade.get("buyer_id")
    )
    await _send(
        bot,
        await _telegram_id(repos, other_id),
        f"📦 <b>Сделка #{trade['id']}</b>\n\n"
        f"{await _name(repos, from_user_id)} отметил(а) получение скинов.\n"
        "Если вы получили свои — нажмите «Получил».",
        web_app_url,
    )


async def cancelled(
    bot: Bot,
    repos: Repositories,
    trade: Dict[str, Any],
    from_user_id: Optional[int],
    web_app_url: Optional[str] = None,
) -> None:
    """Сделку отменили — вторая сторона должна узнать, а не гадать."""
    other_id = (
        trade.get("seller_id") if from_user_id == trade.get("buyer_id") else trade.get("buyer_id")
    )
    await _send(
        bot,
        await _telegram_id(repos, other_id),
        f"❌ <b>Сделка #{trade['id']} отменена</b>\n\n"
        f"{await _name(repos, from_user_id)} закрыл(а) обмен. Объявление снова на доске.",
        web_app_url,
    )


async def finalized(
    bot: Bot, repos: Repositories, trade: Dict[str, Any], web_app_url: Optional[str] = None
) -> None:
    """Trade Protection вышел — можно ставить оценку."""
    for user_id, other_id in (
        (trade.get("buyer_id"), trade.get("seller_id")),
        (trade.get("seller_id"), trade.get("buyer_id")),
    ):
        await _send(
            bot,
            await _telegram_id(repos, user_id),
            f"🏁 <b>Сделка #{trade['id']} закрыта</b>\n\n"
            f"Trade Protection прошёл. Поставьте оценку {await _name(repos, other_id)} — "
            "это помогает остальным выбирать контрагента.",
            web_app_url,
        )


async def stale_trade(
    bot: Bot, repos: Repositories, trade: Dict[str, Any], web_app_url: Optional[str] = None
) -> None:
    """Сделка висит без подтверждения: напомнить, что от сторон ждут шага."""
    title = await _title(repos, trade)
    # напоминаем только той стороне, которая ещё не подтвердила
    pending = [
        user_id
        for role, user_id in (("buyer", trade.get("buyer_id")), ("seller", trade.get("seller_id")))
        if not trade.get(f"{role}_confirmed_at")
    ]
    for user_id in pending:
        await _send(
            bot,
            await _telegram_id(repos, user_id),
            f"⏳ <b>Сделка #{trade['id']} ждёт подтверждения</b>\n\n"
            f"{title}\n"
            "Пока обе стороны не подтвердят, обмен не начнётся. "
            "Если передумали — отмените сделку.",
            web_app_url,
        )
