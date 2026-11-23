"""Хендеры публичных предложений обмена."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from database.repository import Repositories
from bot.keyboards.inline import back_to_main_keyboard

router = Router()


@router.message(Command("offers"))
async def cmd_offers(message: Message, repos: Repositories) -> None:
    offers = await repos.offers.get_active(limit=10)

    if not offers:
        await message.answer(
            "📋 <b>Предложений обмена нет</b>\n\n"
            "Создайте своё первое предложение через /create_offer",
            reply_markup=back_to_main_keyboard(),
        )
        return

    text = "📋 <b>Публичные предложения обмена</b>\n\n"
    for offer in offers:
        text += (
            f"• <b>{offer['title']}</b>\n"
            f"  Продавец: @{offer.get('username') or '-'}\n"
            f"  Рейтинг: {offer.get('rating', 0):.1f} ⭐\n"
            f"  Цена: ${offer.get('price', 0):.2f}\n"
            f"  ID: #{offer['id']}\n\n"
        )

    await message.answer(text, reply_markup=back_to_main_keyboard())


@router.callback_query(F.data == "offers")
async def cb_offers(callback: CallbackQuery, repos: Repositories) -> None:
    offers = await repos.offers.get_active(limit=10)

    if not offers:
        await callback.message.edit_text(
            "📋 <b>Предложений обмена нет</b>\n\n"
            "Создайте своё первое предложение через /create_offer",
            reply_markup=back_to_main_keyboard(),
        )
        await callback.answer()
        return

    text = "📋 <b>Публичные предложения обмена</b>\n\n"
    for offer in offers:
        text += (
            f"• <b>{offer['title']}</b>\n"
            f"  Продавец: @{offer.get('username') or '-'}\n"
            f"  Рейтинг: {offer.get('rating', 0):.1f} ⭐\n"
            f"  Цена: ${offer.get('price', 0):.2f}\n"
            f"  ID: #{offer['id']}\n\n"
        )

    await callback.message.edit_text(text, reply_markup=back_to_main_keyboard())
    await callback.answer()


@router.message(Command("create_offer"))
async def cmd_create_offer(message: Message) -> None:
    await message.answer(
        "📝 <b>Создание предложения обмена</b>\n\n"
        "Функция в разработке (Срез 7).\n"
        "Скоро вы сможете создавать публичные предложения обмена скинами.",
        reply_markup=back_to_main_keyboard(),
    )