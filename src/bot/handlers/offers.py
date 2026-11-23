"""Публичные предложения обмена."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import back_to_main_keyboard, offers_keyboard
from bot.utils.formatters import format_offer
from bot.utils.telegram import edit_or_send, notify
from database.repository import Repositories

router = Router()

EMPTY_TEXT = (
    "📋 <b>Предложений обмена нет</b>\n\n"
    "Создайте своё первое предложение через /create_offer."
)


async def _offers_view(repos: Repositories):
    offers = await repos.offers.get_active(limit=10)
    if not offers:
        return EMPTY_TEXT, back_to_main_keyboard()

    lines = ["📋 <b>Публичные предложения</b>", ""]
    lines.extend(format_offer(offer) + "\n" for offer in offers)
    return "\n".join(lines).rstrip(), offers_keyboard(offers)


@router.message(Command("offers"))
async def cmd_offers(message: Message, repos: Repositories) -> None:
    text, markup = await _offers_view(repos)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "offers")
async def cb_offers(callback: CallbackQuery, repos: Repositories) -> None:
    text, markup = await _offers_view(repos)
    await edit_or_send(callback.message, text, markup)
    await notify(callback)
