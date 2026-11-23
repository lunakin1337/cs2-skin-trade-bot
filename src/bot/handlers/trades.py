"""Хендеры сделок."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from database.repository import Repositories
from bot.keyboards.inline import back_to_main_keyboard

router = Router()


@router.message(Command("trades"))
async def cmd_trades(message: Message, repos: Repositories) -> None:
    user = await repos.users.get_by_telegram_id(message.from_user.id)
    if not user:
        await repos.users.create_or_update(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        user = await repos.users.get_by_telegram_id(message.from_user.id)

    trades = await repos.trades.get_by_user(user["id"], limit=10)

    if not trades:
        await message.answer(
            "🔄 <b>Ваши сделки</b>\n\n"
            "У вас пока нет сделок.\n"
            "Создайте предложение обмена через /create_offer",
            reply_markup=back_to_main_keyboard(),
        )
        return

    text = "🔄 <b>Ваши сделки</b>\n\n"
    for trade in trades:
        text += (
            f"• Сделка #{trade['id']}\n"
            f"  Статус: {trade['status']}\n"
            f"  Покупатель: @{trade.get('buyer_username') or '-'}\n"
            f"  Продавец: @{trade.get('seller_username') or '-'}\n\n"
        )

    await message.answer(text, reply_markup=back_to_main_keyboard())


@router.callback_query(F.data == "trades")
async def cb_trades(callback: CallbackQuery, repos: Repositories) -> None:
    user = await repos.users.get_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Пользователь не найден")
        return

    trades = await repos.trades.get_by_user(user["id"], limit=10)

    if not trades:
        await callback.message.edit_text(
            "🔄 <b>Ваши сделки</b>\n\n"
            "У вас пока нет сделок.\n"
            "Создайте предложение обмена через /create_offer",
            reply_markup=back_to_main_keyboard(),
        )
        await callback.answer()
        return

    text = "🔄 <b>Ваши сделки</b>\n\n"
    for trade in trades:
        text += (
            f"• Сделка #{trade['id']}\n"
            f"  Статус: {trade['status']}\n"
            f"  Покупатель: @{trade.get('buyer_username') or '-'}\n"
            f"  Продавец: @{trade.get('seller_username') or '-'}\n\n"
        )

    await callback.message.edit_text(text, reply_markup=back_to_main_keyboard())
    await callback.answer()