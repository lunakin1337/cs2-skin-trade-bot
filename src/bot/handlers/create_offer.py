"""Создание предложения обмена через FSM."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import back_to_main_keyboard
from bot.states.trade import TradeStates
from bot.utils.formatters import NEWLINE, format_item
from bot.utils.telegram import notify
from bot.utils.users import ensure_user
from database.repository import Repositories

logger = logging.getLogger(__name__)

router = Router()

MAX_OFFER_ITEMS = 10
OFFER_LIST_LIMIT = 15
CATALOG_RESULTS = 5


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
        "📝 <b>Создание предложения</b>"
        + NEWLINE * 2
        + "Шаг 1/4: название предложения (3–100 символов)."
        + NEWLINE
        + "Например: «Продам AK-47 | Redline» или «Меняю нож на скины».",
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
        "Шаг 2/4: опишите предложение."
        + NEWLINE
        + "Одна строка о том, что отдаёте и что хотите получить. «-» — пропустить."
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
    all_items = await repos.items.get_by_owner(user["id"])

    numbered = [
        (position, item)
        for position, item in enumerate(all_items, start=1)
        if item.get("is_tradable")
    ]
    if not numbered:
        await state.clear()
        await message.answer("❌ Торгуемых предметов нет.", reply_markup=back_to_main_keyboard())
        return

    # Номера совпадают с порядком в /inventory, а id остаётся скрытым в состоянии
    await state.update_data(item_map={str(position): item["id"] for position, item in numbered})

    shown = numbered[:OFFER_LIST_LIMIT]
    lines = [
        "Шаг 3/4: выберите скины, которые отдаёте.",
        f"Отправьте номера через запятую (до {MAX_OFFER_ITEMS}), например: <code>1, 3</code>.",
        "Нумерация совпадает с /inventory.",
        "",
        "<b>Торгуемые предметы:</b>",
    ]
    lines.extend(format_item(item, index=position) for position, item in shown)

    if len(numbered) > len(shown):
        lines.append(f"{NEWLINE}... и ещё {len(numbered) - len(shown)} — смотрите /inventory.")
    else:
        lines.append(f"{NEWLINE}Полный список — в /inventory.")

    await message.answer(NEWLINE.join(lines))


@router.message(TradeStates.waiting_items_offered)
async def process_items_offered(
    message: Message,
    state: FSMContext,
    repos: Repositories,
) -> None:
    raw = (message.text or "").replace(" ", "")
    try:
        numbers = list(dict.fromkeys(int(part) for part in raw.split(",") if part))
    except ValueError:
        await message.answer("❌ Нужны числа через запятую, например: 1, 3")
        return

    if not 1 <= len(numbers) <= MAX_OFFER_ITEMS:
        await message.answer(f"❌ Укажите от 1 до {MAX_OFFER_ITEMS} предметов.")
        return

    data = await state.get_data()
    item_map = data.get("item_map") or {}
    unknown = [number for number in numbers if str(number) not in item_map]
    if unknown:
        await message.answer(f"❌ Номеров {unknown} нет в списке. Начните заново: /create_offer")
        return

    item_ids = [item_map[str(number)] for number in numbers]
    user = await ensure_user(repos, message.from_user)
    owned = await repos.items.get_by_owner(user["id"], tradable_only=True)
    owned_ids = {item["id"] for item in owned}

    unavailable = [number for number, item_id in zip(numbers, item_ids) if item_id not in owned_ids]
    if unavailable:
        await message.answer(
            f"❌ Предметы {unavailable} уже недоступны — проданы или на кулдауне. "
            "Обновите список: /create_offer"
        )
        return

    await state.update_data(items_offered=item_ids)
    await state.set_state(TradeStates.waiting_wanted_search)
    await message.answer(
        "Шаг 4/4: что хотите получить?"
        + NEWLINE * 2
        + "Напишите название скина — поищу в каталоге CS2."
        + NEWLINE
        + "Например: <code>AWP Asiimov</code>, <code>нож керамбит</code>, <code>перчатки</code>."
        + NEWLINE * 2
        + "«-» — пропустить и опубликовать без конкретики."
    )


async def _finish_offer(
    message: Message,
    state: FSMContext,
    repos: Repositories,
    wanted_name: str | None,
    wanted_text: str,
) -> None:
    data = await state.get_data()
    user = await ensure_user(repos, message.from_user)

    offer_id = await repos.offers.create(
        creator_id=user["id"],
        title=data["title"],
        items_offered=data["items_offered"],
        items_wanted=wanted_text,
        description=data.get("description"),
        wanted_name=wanted_name,
    )
    await state.clear()

    await message.answer(
        f"✅ Предложение <b>#{offer_id}</b> опубликовано!"
        + NEWLINE * 2
        + f"{data['title']}"
        + NEWLINE
        + f"Отдаёте предметов: {len(data['items_offered'])}"
        + NEWLINE
        + f"Хотите получить: {wanted_name or wanted_text}"
        + NEWLINE * 2
        + "Доска объявлений — /board, свои предложения — /my_offers.",
        reply_markup=back_to_main_keyboard(),
    )


@router.message(TradeStates.waiting_wanted_search)
async def process_wanted_search(
    message: Message,
    state: FSMContext,
    repos: Repositories,
) -> None:
    query = (message.text or "").strip()
    if query == "-":
        await _finish_offer(message, state, repos, None, "Не указано")
        return

    if len(query) < 2:
        await message.answer("❌ Слишком короткий запрос — нужно хотя бы два символа.")
        return

    candidates = await repos.skins.search(query, limit=CATALOG_RESULTS)
    if not candidates:
        await message.answer(
            "❌ В каталоге ничего не нашлось. Уточните название или отправьте «-», чтобы пропустить."
        )
        return

    await state.update_data(
        wanted_query=query,
        candidates={str(index): skin["market_hash_name"] for index, skin in enumerate(candidates, 1)},
    )
    await state.set_state(TradeStates.waiting_wanted_pick)

    lines = ["<b>Нашёл в каталоге:</b>", ""]
    for index, skin in enumerate(candidates, start=1):
        price = f" · {skin['price_text']}" if skin.get("price_text") else ""
        lines.append(f"<code>{index}</code>. {skin['market_hash_name']}{price}")

    lines.append("")
    lines.append("Отправьте номер нужного скина или «-», чтобы пропустить.")

    await message.answer(NEWLINE.join(lines))


@router.message(TradeStates.waiting_wanted_pick)
async def process_wanted_pick(
    message: Message,
    state: FSMContext,
    repos: Repositories,
) -> None:
    answer = (message.text or "").strip()
    data = await state.get_data()
    candidates = data.get("candidates") or {}

    if answer == "-":
        await _finish_offer(message, state, repos, None, data.get("wanted_query") or "Не указано")
        return

    if answer not in candidates:
        await message.answer("❌ Нужен номер из списка или «-», чтобы пропустить.")
        return

    wanted_name = candidates[answer]
    await _finish_offer(message, state, repos, wanted_name, wanted_name)
