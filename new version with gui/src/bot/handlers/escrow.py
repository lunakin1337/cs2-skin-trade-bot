"""Эскроу и споры."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards.inline import back_to_main_keyboard
from database.repository import Repositories

router = Router()

ESCROW_TEXT = (
    "🔒 <b>Эскроу-сделки</b>\n\n"
    "1. Стороны подтверждают сделку в /trades\n"
    "2. Продавец отправляет Steam Trade Offer по Trade URL покупателя\n"
    "3. Покупатель подтверждает получение скинов\n"
    "4. Бот закрывает сделку и открывает взаимные оценки\n\n"
    "Если сторона не отвечает или обмен пошёл не так — /dispute, "
    "спор разберёт администратор.\n\n"
    "Ваши сделки: /trades"
)

ACTIVE_STATUSES = ("pending", "confirmed", "in_escrow")


@router.message(Command("escrow"))
async def cmd_escrow_info(message: Message) -> None:
    await message.answer(ESCROW_TEXT, reply_markup=back_to_main_keyboard())


@router.message(Command("dispute"))
async def cmd_dispute(message: Message, repos: Repositories) -> None:
    user = await repos.users.get_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден")
        return

    trades = await repos.trades.get_by_user(user["id"])
    active = [trade for trade in trades if trade["status"] in ACTIVE_STATUSES]

    if not active:
        await message.answer(
            "❌ У вас нет активных сделок, по которым можно открыть спор.",
            reply_markup=back_to_main_keyboard(),
        )
        return

    lines = ["⚖️ <b>Открытие спора</b>", ""]
    lines.extend(f"• Сделка #{trade['id']} — {trade['status']}" for trade in active)
    lines.append(
        "\nСоздать спор можно через администратора: /help → поддержка.\n"
        "Укажите ID сделки и причину."
    )

    await message.answer("\n".join(lines), reply_markup=back_to_main_keyboard())
