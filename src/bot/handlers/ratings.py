"""Хендеры рейтингов и отзывов (Срез 10)."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from database.repository import Repositories
from bot.keyboards.inline import back_to_main_keyboard

router = Router()


@router.message(Command("rating"))
async def cmd_rating(message: Message, repos: Repositories) -> None:
    user = await repos.users.get_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден")
        return

    ratings = await repos.ratings.get_for_user(user["id"])
    avg = await repos.ratings.get_average_rating(user["id"])

    if not ratings:
        await message.answer(
            f"⭐ <b>Ваш рейтинг</b>\n\n"
            f"Средний рейтинг: {avg:.1f} ⭐\n"
            f"Отзывов: 0\n\n"
            f"Отзывы pojawятся после завершённых сделок.",
            reply_markup=back_to_main_keyboard(),
        )
        return

    text = f"⭐ <b>Ваш рейтинг</b>\n\n"
    text += f"Средний рейтинг: {avg:.1f} ⭐\n"
    text += f"Отзывов: {len(ratings)}\n\n"
    text += "<b>Последние отзывы:</b>\n"
    for r in ratings[:5]:
        text += (
            f"• {r['score']} ⭐ от @{r.get('from_username') or '-'}\n"
            f"  {r.get('comment') or '-'}\n\n"
        )

    await message.answer(text, reply_markup=back_to_main_keyboard())