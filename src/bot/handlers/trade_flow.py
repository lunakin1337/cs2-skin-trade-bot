"""Трейд-флоу: принятие предложения, подтверждение, обмен и завершение."""

import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.handlers.trades import render_trades
from bot.keyboards.inline import back_to_main_keyboard
from bot.utils.telegram import edit_or_send, notify
from bot.utils.users import ensure_user
from database.repository import Repositories

logger = logging.getLogger(__name__)

router = Router()

TRADE_INFO = (
    "🔄 <b>Как проходит обмен</b>\n\n"
    "1. Принимаете предложение в /offers — создаётся сделка\n"
    "2. Обе стороны подтверждают её в /trades\n"
    "3. Открывается кнопка «Обмен» — она ведёт на Steam Trade URL контрагента\n"
    "4. Каждая сторона жмёт «Получил», когда скины на руках\n"
    "5. После этого сделка закрывается и можно поставить оценку\n\n"
    "Если что-то пошло не так — /dispute."
)


@router.message(Command("trade"))
async def cmd_trade_info(message: Message) -> None:
    await message.answer(TRADE_INFO, reply_markup=back_to_main_keyboard())


def _role(trade: dict, user_id: int) -> str | None:
    if trade["buyer_id"] == user_id:
        return "buyer"
    if trade["seller_id"] == user_id:
        return "seller"
    return None


async def _refresh_message(callback: CallbackQuery, repos: Repositories) -> None:
    text, markup = await render_trades(repos, callback.from_user.id)
    await edit_or_send(callback.message, text, markup)


@router.callback_query(F.data.startswith("accept_offer_"))
async def cb_accept_offer(callback: CallbackQuery, repos: Repositories) -> None:
    try:
        offer_id = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        await notify(callback, "Некорректное предложение", alert=True)
        return

    offer = await repos.offers.get_by_id(offer_id)
    if not offer:
        await notify(callback, "Предложение не найдено", alert=True)
        return
    if offer["status"] != "active":
        await notify(callback, "Предложение больше не активно", alert=True)
        return

    user = await ensure_user(repos, callback.from_user)
    if user["id"] == offer["creator_id"]:
        await notify(callback, "Нельзя принять своё предложение", alert=True)
        return
    if not user.get("steam_trade_url"):
        await notify(callback, "Сначала укажите Trade URL в профиле", alert=True)
        return

    trade_id = await repos.trades.create(
        buyer_id=user["id"],
        seller_id=offer["creator_id"],
        offer_id=offer_id,
    )
    for item_id in json.loads(offer["items_offered"] or "[]"):
        await repos.trade_items.add(
            trade_id=trade_id,
            item_id=item_id,
            from_user_id=offer["creator_id"],
            to_user_id=user["id"],
        )
    await repos.offers.update_status(offer_id, "in_trade")

    text, markup = await render_trades(repos, callback.from_user.id)
    await edit_or_send(
        callback.message,
        f"✅ Сделка <b>#{trade_id}</b> создана — подтвердите её.\n\n{text}",
        markup,
    )
    await notify(callback, f"Сделка #{trade_id} создана")


@router.callback_query(F.data.startswith("trade_confirm_"))
async def cb_trade_confirm(callback: CallbackQuery, repos: Repositories) -> None:
    trade_id = _trade_id(callback.data)
    trade = await repos.trades.get_by_id(trade_id) if trade_id else None
    if not trade:
        await notify(callback, "Сделка не найдена", alert=True)
        return

    user = await ensure_user(repos, callback.from_user)
    role = _role(trade, user["id"])
    if role is None:
        await notify(callback, "Это не ваша сделка", alert=True)
        return
    if trade["status"] != "pending":
        await notify(callback, "Сделка уже подтверждена или закрыта", alert=True)
        return

    await repos.trades.set_confirmed(trade_id, role)
    trade = await repos.trades.get_by_id(trade_id)

    if trade["buyer_confirmed_at"] and trade["seller_confirmed_at"]:
        await repos.trades.update_status(trade_id, "in_escrow")
        await _refresh_message(callback, repos)
        await notify(callback, "Обе стороны подтвердили — можно обмениваться")
        return

    await _refresh_message(callback, repos)
    await notify(callback, "Ждём подтверждения второй стороны")


@router.callback_query(F.data.startswith("trade_complete_"))
async def cb_trade_complete(callback: CallbackQuery, repos: Repositories) -> None:
    trade_id = _trade_id(callback.data)
    trade = await repos.trades.get_by_id(trade_id) if trade_id else None
    if not trade:
        await notify(callback, "Сделка не найдена", alert=True)
        return

    user = await ensure_user(repos, callback.from_user)
    role = _role(trade, user["id"])
    if role is None:
        await notify(callback, "Это не ваша сделка", alert=True)
        return
    if trade["status"] != "in_escrow":
        await notify(callback, "Сделка ещё не готова к завершению", alert=True)
        return
    if trade.get(f"{role}_completed_at"):
        await notify(callback, "Вы уже отметили получение", alert=True)
        return

    await repos.trades.set_completed_side(trade_id, role)
    trade = await repos.trades.get_by_id(trade_id)

    if trade["buyer_completed_at"] and trade["seller_completed_at"]:
        await repos.trades.mark_completed(trade_id)
        for participant in (trade["buyer_id"], trade["seller_id"]):
            await repos.users.increment_trades_count(participant)
        if trade.get("offer_id"):
            await repos.offers.update_status(trade["offer_id"], "completed")
        await _refresh_message(callback, repos)
        await notify(callback, "Сделка завершена — поставьте оценку контрагенту")
        return

    await _refresh_message(callback, repos)
    await notify(callback, "Отметили получение, ждём вторую сторону")


@router.callback_query(F.data.startswith("trade_cancel_"))
async def cb_trade_cancel(callback: CallbackQuery, repos: Repositories) -> None:
    trade_id = _trade_id(callback.data)
    trade = await repos.trades.get_by_id(trade_id) if trade_id else None
    if not trade:
        await notify(callback, "Сделка не найдена", alert=True)
        return

    user = await ensure_user(repos, callback.from_user)
    if _role(trade, user["id"]) is None:
        await notify(callback, "Это не ваша сделка", alert=True)
        return
    if trade["status"] not in {"pending", "confirmed", "in_escrow"}:
        await notify(callback, "Сделку уже нельзя отменить", alert=True)
        return

    await repos.trades.update_status(trade_id, "cancelled")
    if trade.get("offer_id"):
        await repos.offers.update_status(trade["offer_id"], "active")

    await _refresh_message(callback, repos)
    await notify(callback, "Сделка отменена, предложение снова активно")


def _trade_id(callback_data: str) -> int | None:
    try:
        return int(callback_data.rsplit("_", 1)[-1])
    except ValueError:
        return None
