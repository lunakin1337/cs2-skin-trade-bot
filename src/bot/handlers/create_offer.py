"""Создание предложения обмена через FSM."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import back_to_main_keyboard
from bot.states.trade import TradeStates
from bot.utils.formatters import format_item
from bot.utils.telegram import notify
from bot.utils.users import ensure_user
from database.repository import Repositories

logger = logging.getLogger(__name__)

router = Router()

MAX_OFFER_ITEMS = 10
OFFER_LIST_LIMIT = 15


async def _start_offer(target, repos: Repositories, state: FSMContext, user) -> None:
    db_user = await ensure_user(repos, user)
    if not db_user.get("is_steam_linked"):
        await target.answer(
            "❌ Сначала привяжите Steam аккаунт в профиле и синхронизируйте инвентарь.",
            reply_markup=back_to_main_keyboard(),
        )
        return

    items = await repos.items.get_by_owner(db_user["id"], tradable_only=True)
    if not items:
        await target.answer(
            "❌ Нет торгуемых скинов. Синхронизируйте инвентарь в профиле.",
            reply_markup=back_to_main_keyboard(),
        )
        return

    await state.set_state(TradeStates.waiting_offer_title)
    await target.answer(
        "📝 <b>Создание предложения</b>\n\n"
        "Шаг 1/4: название предложения (3–100 символов).\n"
        "Например: «Продам AK-47 | Redline» или «Меняю нож на скины».",
        reply_markup=back_to_main_keyboard(),
    )


@router.message(Command("create_offer"))
async def cmd_create_offer(message: Message, state: FSMContext, repos: Repositories) -> None:
    await _start_offer(message, repos, state, message.from_user)


@router.callback_query(F.data == "create_offer")
async def cb_create_offer(callback: CallbackQuery, state: FSMContext, repos: Repositories) -> None:
    await _start_offer(callback.message, repos, state, callback.from_user)
    await notify(callback)


@router.message(TradeStates.waiting_offer_title)
async def process_offer_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not 3 <= len(title) <= 100:
        await message.answer("❌ Название должно быть от 3 до 100 символов. Попробуйте снова.")
        return

    await state.update_data(title=title)
    await state.set_state(TradeStates.waiting_offer_description)
    await message.answer(
        "Шаг 2/4: опишите предложение.\n"
        "Одна строка о том, что отдаёте и что хотите получить. «-» — пропустить."
    )


@router.message(TradeStates.waiting_offer_description)
async def process_offer_description(
    message: Message,
    state: FSMContext,
    repos: Repositories,
) -> None:
    description = (message.text or "").strip()
    await state.update_data(description=None if description == "-" else description)
    await state.set_state(TradeStates.waiting_items_offered)

    user = await ensure_user(repos, message.from_user)
    items = await repos.items.get_by_owner(user["id"], tradable_only=True, limit=OFFER_LIST_LIMIT)

    if not items:
        await state.clear()
        await message.answer("❌ Торгуемых предметов нет.", reply_markup=back_to_main_keyboard())
        return

    lines = [
        "Шаг 3/4: выберите скины, которые отдаёте.",
        f"Отправьте ID через запятую (до {MAX_OFFER_ITEMS}), например: <code>1, 5, 12</code>.",
        "",
        "<b>Торгуемые предметы:</b>",
    ]
    lines.extend(format_item(item, index=item["id"]) for item in items)
    lines.append("\nПолный список — в /inventory.")

    await message.answer("\n".join(lines))


@router.message(TradeStates.waiting_items_offered)
async def process_items_offered(
    message: Message,
    state: FSMContext,
    repos: Repositories,
) -> None:
    raw = (message.text or "").replace(" ", "")
    try:
        item_ids = [int(part) for part in raw.split(",") if part]
    except ValueError:
        await message.answer("❌ Нужны числовые ID через запятую.")
        return

    if not 1 <= len(item_ids) <= MAX_OFFER_ITEMS:
        await message.answer(f"❌ Укажите от 1 до {MAX_OFFER_ITEMS} предметов.")
        return

    user = await ensure_user(repos, message.from_user)
    owned = await repos.items.get_by_owner(user["id"], tradable_only=True)
    owned_ids = {item["id"] for item in owned}

    invalid = [item_id for item_id in item_ids if item_id not in owned_ids]
    if invalid:
        await message.answer(
            f"❌ Предметы {invalid} не найдены среди торгуемых. Проверьте ID в /inventory."
        )
        return

    await state.update_data(items_offered=item_ids)
    await state.set_state(TradeStates.waiting_items_wanted)
    await message.answer(
        "Шаг 4/4: что хотите получить в обмен?\n"
        "Например: «AWP | Dragon Lore» или «скины на $50». «-» — пропустить."
    )


@router.message(TradeStates.waiting_items_wanted)
async def process_items_wanted(
    message: Message,
    state: FSMContext,
    repos: Repositories,
) -> None:
    wanted = (message.text or "").strip()
    data = await state.get_data()

    user = await ensure_user(repos, message.from_user)
    offer_id = await repos.offers.create(
        creator_id=user["id"],
        title=data["title"],
        items_offered=data["items_offered"],
        items_wanted="Не указано" if wanted == "-" else wanted,
        description=data.get("description"),
    )
    await state.clear()

    await message.answer(
        f"✅ Предложение <b>#{offer_id}</b> опубликовано!\n\n"
        f"{data['title']}\n"
        f"Отдаёте предметов: {len(data['items_offered'])}\n"
        f"Хотите получить: {'Не указано' if wanted == '-' else wanted}\n\n"
        "Смотреть все предложения — /offers.",
        reply_markup=back_to_main_keyboard(),
    )
