"""Трейд-флоу: принятие предложения, подтверждение, обмен и завершение."""

import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.handlers.trades import render_trades
from bot.keyboards.inline import back_to_main_keyboard
from bot.services.disputes import DisputeError, notify_dispute, open_dispute
from bot.services.trades import settle_after_receipt
from bot.states.trade import DisputeStates
from bot.utils.formatters import NEWLINE, format_deadline
from bot.utils.telegram import edit_or_send, notify
from bot.utils.users import ensure_user
from config.settings import BotConfig
from database.repository import Repositories

logger = logging.getLogger(__name__)

router = Router()

TRADE_INFO = (
    "🔄 <b>Как проходит обмен</b>\n\n"
    "1. Принимаете предложение в /offers — создаётся сделка\n"
    "2. Обе стороны подтверждают её в /trades\n"
    "3. Открывается кнопка «Обмен» — она ведёт на Steam Trade URL контрагента\n"
    "4. Каждая сторона жмёт «Получил», когда скины на руках\n"
    "5. Дальше сделка ещё 7 дней под Trade Protection: предметы нельзя передать или\n"
    "   продать, а отправитель может отменить трейд — сделка ждёт этот срок\n"
    "6. Когда срок истёк, сделка закрывается сама и появляется оценка\n\n"
    "Если трейд откатили в Steam — кнопка «↩️ Трейд отменён»: сделка уходит в\n"
    "«отменена», счётчики и оценки не меняются. Остальные проблемы — /dispute."
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
    # инициатор подтверждает сразу — ждём только автора объявления
    await repos.trades.set_confirmed(trade_id, "buyer")
    await repos.offers.update_status(offer_id, "in_trade")

    text, markup = await render_trades(repos, callback.from_user.id)
    await edit_or_send(
        callback.message,
        f"✅ Предложение по обмену <b>#{trade_id}</b> отправлено.\n"
        "Ваше подтверждение уже учтено — ждём автора объявления.\n\n" + text,
        markup,
    )
    await notify(callback, f"Предложение #{trade_id} отправлено")


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
    trade = await settle_after_receipt(repos, trade)

    if trade["status"] == "holding":
        deadline = format_deadline(trade.get("finalize_at"))
        await _refresh_message(callback, repos)
        await notify(
            callback,
            f"Оба получили скины. Сделка закроется {deadline}: до этого предметы под "
            "Trade Protection и отправитель может отменить трейд.",
        )
        return

    await _refresh_message(callback, repos)
    await notify(callback, "Отметили получение, ждём вторую сторону")


def dispute_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Не открывать спор", callback_data="trade_dispute_cancel")]]
    )


@router.callback_query(F.data.startswith("trade_dispute_"))
async def cb_trade_dispute(
    callback: CallbackQuery, repos: Repositories, state: FSMContext
) -> None:
    if callback.data == "trade_dispute_cancel":
        await state.clear()
        await edit_or_send(callback.message, "Спор не открыт.", back_to_main_keyboard())
        await notify(callback)
        return

    trade_id = _trade_id(callback.data)
    trade = await repos.trades.get_by_id(trade_id) if trade_id else None
    if not trade:
        await notify(callback, "Сделка не найдена", alert=True)
        return

    user = await ensure_user(repos, callback.from_user)
    if _role(trade, user["id"]) is None:
        await notify(callback, "Это не ваша сделка", alert=True)
        return
    if await repos.disputes.get_open_by_trade(trade_id):
        await notify(callback, "По этой сделке уже открыт спор", alert=True)
        return

    await state.set_state(DisputeStates.waiting_reason)
    await state.update_data(dispute_trade_id=trade_id)
    await edit_or_send(
        callback.message,
        f"⚠️ <b>Спор по сделке #{trade_id}</b>"
        + NEWLINE
        + NEWLINE
        + "Опишите одним сообщением, что пошло не так: что именно не пришло, "
        "кто и когда отправил обмен, чем это подтверждается."
        + NEWLINE
        + "Спор увидит администратор и вторая сторона.",
        dispute_cancel_keyboard(),
    )
    await notify(callback)


@router.message(DisputeStates.waiting_reason)
async def msg_dispute_reason(
    message: Message, repos: Repositories, state: FSMContext, config: BotConfig
) -> None:
    data = await state.get_data()
    trade_id = data.get("dispute_trade_id")
    user = await ensure_user(repos, message.from_user)
    if not trade_id:
        await state.clear()
        await message.answer("Черновик спора потерялся — откройте его заново в /trades.",
                             reply_markup=back_to_main_keyboard())
        return

    try:
        dispute_id, trade = await open_dispute(repos, int(trade_id), user["id"], message.text or "")
    except DisputeError as error:
        await state.clear()
        await message.answer(f"❌ {error}", reply_markup=back_to_main_keyboard())
        return

    await state.clear()
    await notify_dispute(
        message.bot, repos, trade, dispute_id, user["id"], message.text or "", config.admin_ids
    )
    await message.answer(
        f"⚖️ Спор #{dispute_id} по сделке #{trade_id} открыт."
        + NEWLINE
        + "Администратор и вторая сторона получили уведомление.",
        reply_markup=back_to_main_keyboard(),
    )


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


@router.callback_query(F.data.startswith("trade_rollback_"))
async def cb_trade_rollback(callback: CallbackQuery, repos: Repositories) -> None:
    """Контрагент отменил трейд в Steam: сделка возвращается в cancelled без счётчиков."""
    trade_id = _trade_id(callback.data)
    trade = await repos.trades.get_by_id(trade_id) if trade_id else None
    if not trade:
        await notify(callback, "Сделка не найдена", alert=True)
        return

    user = await ensure_user(repos, callback.from_user)
    if _role(trade, user["id"]) is None:
        await notify(callback, "Это не ваша сделка", alert=True)
        return
    if trade["status"] != "holding":
        await notify(callback, "Сделка не ждёт окончания Trade Protection", alert=True)
        return

    await repos.trades.update_status(trade_id, "cancelled")
    if trade.get("offer_id"):
        await repos.offers.update_status(trade["offer_id"], "active")

    await _refresh_message(callback, repos)
    await notify(
        callback,
        "Сделка отменена: трейд откатили в Steam. Счётчики сделок и оценки не изменились.",
    )


def _trade_id(callback_data: str) -> int | None:
    try:
        return int(callback_data.rsplit("_", 1)[-1])
    except ValueError:
        return None
