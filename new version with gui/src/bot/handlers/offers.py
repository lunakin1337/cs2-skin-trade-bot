"""Доска предложений и собственные объявления."""

import html
import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import back_to_main_keyboard, board_keyboard, my_offers_keyboard
from bot.utils.formatters import NEWLINE, format_offer_card
from bot.utils.telegram import edit_or_send, notify
from bot.utils.users import ensure_user
from database.repository import Repositories

logger = logging.getLogger(__name__)

router = Router()

BOARD_PAGE_SIZE = 3

EMPTY_BOARD = (
    "📋 <b>Доска пуста</b>"
    + NEWLINE * 2
    + "Объявлений пока нет. Создайте первое: /create_offer."
)

EMPTY_MY_OFFERS = (
    "📂 <b>Мои предложения</b>"
    + NEWLINE * 2
    + "У вас пока нет объявлений. Создать: /create_offer."
)


async def _offer_cards(repos: Repositories, offers: list[dict]) -> str:
    cards = []
    for offer in offers:
        try:
            item_ids = json.loads(offer.get("items_offered") or "[]")
        except ValueError:
            item_ids = []
        items = await repos.items.get_by_ids(item_ids)
        cards.append(format_offer_card(offer, items, 0))
    return (NEWLINE * 2).join(cards)


async def board_view(repos: Repositories, page: int = 0, viewer_telegram_id: int | None = None):
    total = await repos.offers.count_active()
    if not total:
        return EMPTY_BOARD, back_to_main_keyboard()

    pages = max(1, -(-total // BOARD_PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    offers = await repos.offers.get_active(limit=BOARD_PAGE_SIZE, offset=page * BOARD_PAGE_SIZE)

    cards = await _offer_cards(repos, offers)
    text = (
        f"📋 <b>Доска обменов</b> · {total} предложений"
        + NEWLINE
        + f"<pre>{html.escape(cards)}</pre>"
    )
    return text, board_keyboard(offers, page, pages, viewer_telegram_id)


async def my_offers_view(repos: Repositories, from_user):
    user = await ensure_user(repos, from_user)
    if user is None:
        return "🚫 Ваш аккаунт заблокирован. Напишите администратору, если считаете это ошибкой.", back_to_main_keyboard()
    offers = await repos.offers.get_by_creator(user["id"])
    if not offers:
        return EMPTY_MY_OFFERS, back_to_main_keyboard()

    active = [offer for offer in offers if offer["status"] == "active"]
    cards = await _offer_cards(repos, offers[:3])

    lines = [
        "📂 <b>Мои предложения</b>",
        f"Всего: {len(offers)} · активных: {len(active)}",
    ]
    if offers[0].get("status") != "active":
        statuses = ", ".join(f"#{offer['id']} {offer['status']}" for offer in offers[:5])
        lines.append(f"Статусы: {statuses}")

    text = NEWLINE.join(lines) + NEWLINE * 2 + f"<pre>{html.escape(cards)}</pre>"
    return text, my_offers_keyboard(offers[:5])


@router.message(Command("board"))
async def cmd_board(message: Message, repos: Repositories) -> None:
    text, markup = await board_view(repos, viewer_telegram_id=message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.message(Command("offers"))
async def cmd_offers_alias(message: Message, repos: Repositories) -> None:
    text, markup = await board_view(repos, viewer_telegram_id=message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "offers")
async def cb_offers_alias(callback: CallbackQuery, repos: Repositories) -> None:
    text, markup = await board_view(repos, viewer_telegram_id=callback.from_user.id)
    await edit_or_send(callback.message, text, markup)
    await notify(callback)


@router.callback_query(F.data == "board")
async def cb_board(callback: CallbackQuery, repos: Repositories) -> None:
    text, markup = await board_view(repos, viewer_telegram_id=callback.from_user.id)
    await edit_or_send(callback.message, text, markup)
    await notify(callback)


@router.callback_query(F.data.startswith("board_"))
async def cb_board_page(callback: CallbackQuery, repos: Repositories) -> None:
    tail = callback.data.rsplit("_", 1)[-1]
    if tail == "noop":
        await notify(callback)
        return

    try:
        page = int(tail)
    except ValueError:
        page = 0

    text, markup = await board_view(repos, page, callback.from_user.id)
    await edit_or_send(callback.message, text, markup)
    await notify(callback)


@router.message(Command("my_offers"))
async def cmd_my_offers(message: Message, repos: Repositories) -> None:
    text, markup = await my_offers_view(repos, message.from_user)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "my_offers")
async def cb_my_offers(callback: CallbackQuery, repos: Repositories) -> None:
    text, markup = await my_offers_view(repos, callback.from_user)
    await edit_or_send(callback.message, text, markup)
    await notify(callback)


@router.callback_query(F.data.startswith("offer_delete_"))
async def cb_offer_delete(callback: CallbackQuery, repos: Repositories) -> None:
    try:
        offer_id = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        await notify(callback, "Некорректное предложение", alert=True)
        return

    offer = await repos.offers.get_by_id(offer_id)
    user = await ensure_user(repos, callback.from_user)
    if user is None:
        await notify(callback, "Ваш аккаунт заблокирован", alert=True)
        return

    if not offer or offer["creator_id"] != user["id"]:
        await notify(callback, "Это не ваше предложение", alert=True)
        return

    await repos.offers.delete(offer_id)
    text, markup = await my_offers_view(repos, callback.from_user)
    await edit_or_send(callback.message, text, markup)
    await notify(callback, f"Предложение #{offer_id} удалено")


@router.callback_query(F.data.startswith("offer_cancel_"))
async def cb_offer_cancel(callback: CallbackQuery, repos: Repositories) -> None:
    try:
        offer_id = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        await notify(callback, "Некорректное предложение", alert=True)
        return

    offer = await repos.offers.get_by_id(offer_id)
    user = await ensure_user(repos, callback.from_user)
    if user is None:
        await notify(callback, "Ваш аккаунт заблокирован", alert=True)
        return

    if not offer or offer["creator_id"] != user["id"]:
        await notify(callback, "Это не ваше предложение", alert=True)
        return
    if offer["status"] != "active":
        await notify(callback, f"Предложение уже {offer['status']}", alert=True)
        return

    await repos.offers.update_status(offer_id, "cancelled")
    text, markup = await my_offers_view(repos, callback.from_user)
    await edit_or_send(callback.message, text, markup)
    await notify(callback, f"Предложение #{offer_id} снято")
