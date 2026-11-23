"""Хендеры эскроу и Steam Trade Offers (Срез 9)."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from database.repository import Repositories
from bot.keyboards.inline import back_to_main_keyboard

router = Router()


@router.message(Command("escrow"))
async def cmd_escrow_info(message: Message) -> None:
    await message.answer(
        "🔒 <b>Эскроу-сделки</b>\n\n"
        "Как работает эскроу:\n"
        "1. Продавец передаёт скины боту (через Steam Trade Offer)\n"
        "2. Покупатель подтверждает получение\n"
        "3. Бот передаёт скины покупателю\n"
        "4. Сделка завершается\n\n"
        "Если одна из сторон не подтверждает в течение таймаута,\n"
        "сделка отменяется и скины возвращаются владельцу.\n\n"
        "Команды:\n"
        "/trades — ваши сделки\n"
        "/dispute — открыть спор",
        reply_markup=back_to_main_keyboard(),
    )


@router.message(Command("dispute"))
async def cmd_dispute(message: Message, repos: Repositories) -> None:
    user = await repos.users.get_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден")
        return

    trades = await repos.trades.get_by_user(user["id"])
    active = [t for t in trades if t["status"] in ("pending", "confirmed", "in_escrow")]

    if not active:
        await message.answer(
            "❌ У вас нет активных сделок для открытия спора",
            reply_markup=back_to_main_keyboard(),
        )
        return

    text = "⚖️ <b>Открытие спора</b>\n\n"
    for trade in active:
        text += (
            f"• Сделка #{trade['id']} — статус: {trade['status']}\n"
        )

    text += "\nЧтобы открыть спор, обратитесь к администратору.\n"
    text += "Укажите ID сделки и причину спора."

    await message.answer(text, reply_markup=back_to_main_keyboard())