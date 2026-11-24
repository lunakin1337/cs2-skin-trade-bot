"""Создание предложения за три шага: скины → «хочу» → подтверждение."""

import difflib
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import back_to_main_keyboard, draft_keyboard
from bot.states.trade import TradeStates
from bot.utils.formatters import NEWLINE, format_item, format_offer_card, short_name
from bot.utils.skin_query import parse_query
from bot.utils.telegram import notify
from bot.utils.users import ensure_user
from database.repository import Repositories

logger = logging.getLogger(__name__)

router = Router()

MAX_OFFER_ITEMS = 10
OFFER_LIST_LIMIT = 15
CANDIDATES = 3
FUZZY_THRESHOLD = 0.45


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

    all_items = await repos.items.get_by_owner(db_user["id"])
    numbered = [
        (position, item)
        for position, item in enumerate(all_items, start=1)
        if item.get("is_tradable")
    ]
    await state.update_data(item_map={str(position): item["id"] for position, item in numbered})
    await state.set_state(TradeStates.waiting_items_offered)

    lines = [
        "📝 <b>Шаг 1/3 — что отдаёте</b>",
        f"Отправьте номера через запятую (до {MAX_OFFER_ITEMS}), например: <code>1, 3</code>.",
        "Нумерация совпадает с /inventory.",
        "",
    ]
    lines.extend(format_item(item, index=position) for position, item in numbered[:OFFER_LIST_LIMIT])
    if len(numbered) > OFFER_LIST_LIMIT:
        lines.append(f"{NEWLINE}... и ещё {len(numbered) - OFFER_LIST_LIMIT} — смотрите /inventory.")

    await target.answer(NEWLINE.join(lines), reply_markup=back_to_main_keyboard())


@router.message(Command("create_offer"))
async def cmd_create_offer(message: Message, state: FSMContext, repos: Repositories) -> None:
    await _start_offer(message, repos, state, message.from_user)


@router.callback_query(F.data == "create_offer")
async def cb_create_offer(callback: CallbackQuery, state: FSMContext, repos: Repositories) -> None:
    await _start_offer(callback.message, repos, state, callback.from_user)
    await notify(callback)


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
    await state.set_state(TradeStates.waiting_wanted)
    await message.answer(
        "🎯 <b>Шаг 2/3 — что хотите получить</b>"
        + NEWLINE * 2
        + "Опишите словами, как удобно:"
        + NEWLINE
        + "• <code>асимов мв</code>"
        + NEWLINE
        + "• <code>нож керамбит до 500$</code>"
        + NEWLINE
        + "• <code>перчатки</code>, <code>стикер катовице</code>"
        + NEWLINE * 2
        + "«-» — опубликовать без конкретики."
    )


async def _find_candidates(repos: Repositories, text: str) -> list[dict]:
    parsed = parse_query(text)
    found = await repos.skins.search_structured(
        parsed.tokens,
        wear=parsed.wear,
        max_price=parsed.max_price,
        stattrak=parsed.stattrak,
        limit=CANDIDATES,
    )
    if found or not parsed.tokens:
        return found

    # «нож керамбит»: если ножей в каталоге ещё нет, пробуем без категории,
    # но без графити/стикеров — человек просит оружие, а не наклейку
    if "★" in parsed.tokens and len(parsed.tokens) > 1:
        relaxed = await repos.skins.search_structured(
            [token for token in parsed.tokens if token != "★"],
            wear=parsed.wear,
            max_price=parsed.max_price,
            limit=CANDIDATES * 2,
        )
        weapons = [
            row for row in relaxed
            if not any(word in row["market_hash_name"] for word in ("Graffiti", "Sticker", "Capsule"))
        ]
        if weapons:
            return weapons[:CANDIDATES]

    # опечатки и незнакомые сокращения — ищем ближайшие названия
    names = await repos.skins.all_names()
    query = " ".join(parsed.tokens).lower()
    scored = difflib.get_close_matches(query, [name.lower() for name in names], n=CANDIDATES, cutoff=FUZZY_THRESHOLD)
    if not scored:
        return []

    matched = []
    for needle in scored:
        for name in names:
            if name.lower() == needle:
                matched.append({"market_hash_name": name, "price_text": None})
                break
    return matched


async def _show_preview(
    target: Message,
    state: FSMContext,
    repos: Repositories,
    candidates: list[dict],
    wanted_text: str,
) -> None:
    data = await state.get_data()
    items = await repos.items.get_by_ids(data.get("items_offered") or [])
    wanted = candidates[0]["market_hash_name"] if candidates else (wanted_text or "—")

    await state.update_data(
        wanted_name=candidates[0]["market_hash_name"] if candidates else None,
        wanted_text=wanted_text,
        candidates=[candidate["market_hash_name"] for candidate in candidates],
    )
    await state.set_state(TradeStates.waiting_confirm)

    preview = {
        "id": 0,
        "username": None,
        "rating": 0,
        "description": None if wanted_text == "-" else wanted_text,
        "wanted_name": wanted,
    }
    card = format_offer_card(preview, items, 0).replace("#0 · @— · 0.0⭐", "черновик")

    await target.answer(
        "👀 <b>Шаг 3/3 — проверьте объявление</b>"
        + NEWLINE * 2
        + f"<pre>{card}</pre>",
        reply_markup=draft_keyboard(bool(candidates)),
    )


@router.message(TradeStates.waiting_wanted)
async def process_wanted(message: Message, state: FSMContext, repos: Repositories) -> None:
    text = (message.text or "").strip()
    if text == "-":
        await _show_preview(message, state, repos, [], "-")
        return

    if len(text) < 2:
        await message.answer("❌ Слишком коротко. Опишите хотя бы двумя символами или «-».")
        return

    candidates = await _find_candidates(repos, text)
    if not candidates:
        await message.answer(
            "❌ Не нашёл такого скина в каталоге."
            + NEWLINE
            + "Попробуйте иначе: <code>asiimov</code>, <code>karambit</code>, <code>стикер</code>, "
            "или «-», чтобы опубликовать без конкретики."
        )
        return

    await _show_preview(message, state, repos, candidates, text)


async def _publish(message: Message, state: FSMContext, repos: Repositories) -> None:
    data = await state.get_data()
    user = await ensure_user(repos, message.from_user)

    items = await repos.items.get_by_ids(data.get("items_offered") or [])
    wanted_name = data.get("wanted_name")
    wanted_text = data.get("wanted_text") or "Не указано"

    if not wanted_name and wanted_text == "-":
        wanted_text = "Не указано"

    title = short_name(items[0]["market_hash_name"]) if items else "Обмен"
    if wanted_name:
        title = f"{title} → {short_name(wanted_name)}"
    title = title[:100]

    offer_id = await repos.offers.create(
        creator_id=user["id"],
        title=title,
        items_offered=data.get("items_offered") or [],
        items_wanted=wanted_name or wanted_text,
        description=None if wanted_text == "-" else wanted_text,
        wanted_name=wanted_name,
    )
    await state.clear()

    await message.answer(
        f"✅ Объявление <b>#{offer_id}</b> на доске!"
        + NEWLINE * 2
        + f"{title}"
        + NEWLINE
        + f"Отдаёте: {len(items)} шт."
        + NEWLINE
        + f"Хотите: {wanted_name or wanted_text}"
        + NEWLINE * 2
        + "Смотреть — /board, снять — /my_offers.",
        reply_markup=back_to_main_keyboard(),
    )


@router.callback_query(F.data == "draft_publish")
async def cb_draft_publish(callback: CallbackQuery, state: FSMContext, repos: Repositories) -> None:
    if await state.get_state() != TradeStates.waiting_confirm.state:
        await notify(callback, "Черновик устарел, начните заново", alert=True)
        return

    await _publish(callback.message, state, repos)
    await notify(callback, "Опубликовано")


@router.callback_query(F.data == "draft_retry")
async def cb_draft_retry(callback: CallbackQuery, state: FSMContext, repos: Repositories) -> None:
    await state.set_state(TradeStates.waiting_wanted)
    await callback.message.answer("🎯 Опишите «хочу» иначе — я поищу снова. «-» — без конкретики.")
    await notify(callback)


@router.callback_query(F.data == "draft_cancel")
async def cb_draft_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Черновик удалён. /create_offer — начать заново.")
    await notify(callback)
