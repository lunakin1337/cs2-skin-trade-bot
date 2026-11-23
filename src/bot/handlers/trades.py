"""Список сделок пользователя."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.keyboards.inline import back_to_main_keyboard, trades_keyboard
from bot.utils.formatters import format_trade
from bot.utils.telegram import edit_or_send, notify
from bot.utils.users import ensure_user
from database.repository import Repositories

router = Router()

EMPTY_TEXT = (
    "🔄 <b>Ваши сделки</b>\n\n"
    "Сделок пока нет. Создайте предложение через /create_offer "
    "или примите чужое в /offers."
)


async def render_trades(repos: Repositories, telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Текст и кнопки раздела сделок для конкретного пользователя."""
    user = await repos.users.get_by_telegram_id(telegram_id)
    if not user:
        return "Пользователь не найден", back_to_main_keyboard()

    trades = await repos.trades.get_by_user(user["id"], limit=10)
    if not trades:
        return EMPTY_TEXT, back_to_main_keyboard()

    blocks = [format_trade(trade, user["id"]) for trade in trades]
    return "\n\n".join(["🔄 <b>Ваши сделки</b>", *blocks]), trades_keyboard(trades, user["id"])


@router.message(Command("trades"))
async def cmd_trades(message: Message, repos: Repositories) -> None:
    await ensure_user(repos, message.from_user)
    text, markup = await render_trades(repos, message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "trades")
async def cb_trades(callback: CallbackQuery, repos: Repositories) -> None:
    await ensure_user(repos, callback.from_user)
    text, markup = await render_trades(repos, callback.from_user.id)
    await edit_or_send(callback.message, text, markup)
    await notify(callback)
