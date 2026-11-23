"""Хендер создания предложения обмена (Срез 7)."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.states.trade import TradeStates
from database.repository import Repositories
from bot.keyboards.inline import back_to_main_keyboard
from bot.utils.prices import get_price_fetcher
from bot.utils.formatters import format_item_with_price

router = Router()


@router.message(Command("create_offer"))
async def cmd_create_offer(message: Message, state: FSMContext, repos: Repositories) -> None:
    user = await repos.users.get_by_telegram_id(message.from_user.id)
    if not user:
        await repos.users.create_or_update(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        user = await repos.users.get_by_telegram_id(message.from_user.id)

    if not user.get("is_steam_linked"):
        await message.answer(
            "❌ Сначала привяжите Steam аккаунт через /profile",
            reply_markup=back_to_main_keyboard(),
        )
        return

    items = await repos.items.get_by_owner(user["id"], tradable_only=True)
    if not items:
        await message.answer(
            "❌ У вас нет торгуемых скинов в инвентаре",
            reply_markup=back_to_main_keyboard(),
        )
        return

    await state.set_state(TradeStates.waiting_offer_title)
    await message.answer(
        "📝 <b>Создание предложения обмена</b>\n\n"
        "Шаг 1/4: Введите название предложения\n\n"
        "Например: «Продам AK-47 | Redline» или «Обменю нож на скины»",
        reply_markup=back_to_main_keyboard(),
    )


@router.message(TradeStates.waiting_offer_title)
async def process_offer_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if len(title) < 3 or len(title) > 100:
        await message.answer(
            "❌ Название должно быть от 3 до 100 символов. Попробуйте снова."
        )
        return

    await state.update_data(title=title)
    await state.set_state(TradeStates.waiting_offer_description)
    await message.answer(
        "📝 Шаг 2/4: Введите описание предложения\n\n"
        "Опишите, какие скины вы отдаёте и что хотите получить в обмен.\n"
        "Можно пропустить, отправив «-»."
    )


@router.message(TradeStates.waiting_offer_description)
async def process_offer_description(message: Message, state: FSMContext) -> None:
    description = message.text.strip()
    if description == "-":
        description = None

    await state.update_data(description=description)
    await state.set_state(TradeStates.waiting_items_offered)
    
    # Показываем инвентарь с ценами для выбора
    user = await repos.users.get_by_telegram_id(message.from_user.id)
    items = await repos.items.get_by_owner(user["id"], tradable_only=True)
    
    if not items:
        await message.answer("❌ Инвентарь пуст", reply_markup=back_to_main_keyboard())
        return
    
    # Получаем цены для предметов
    price_fetcher = await get_price_fetcher()
    market_names = [item["market_hash_name"] for item in items if item.get("market_hash_name")]
    prices = await price_fetcher.fetch_multiple(market_names)
    
    text = "📝 Шаг 3/4: Выберите скины, которые вы отдаёте\n\n"
    text += "Введите ID предметов через запятую (например: 1, 5, 12)\n\n"
    text += "<b>Ваш инвентарь:</b>\n"
    
    for item in items[:15]:
        price_info = ""
        if item.get("market_hash_name"):
            price_data = prices.get(item["market_hash_name"])
            if price_data and price_data.best_price_usd:
                price_info = f" | ${price_data.best_price_usd:.2f}"
        
        text += f"  <code>{item['id']}</code>. {item.get('market_hash_name', 'Unknown')}{price_info}\n"
    
    if len(items) > 15:
        text += f"\n... и ещё {len(items) - 15} предметов"
    
    await message.answer(text)


@router.message(TradeStates.waiting_items_offered)
async def process_items_offered(message: Message, state: FSMContext, repos: Repositories) -> None:
    try:
        item_ids = [int(x.strip()) for x in message.text.split(",") if x.strip()]
    except ValueError:
        await message.answer("❌ Неверный формат. Введите числа через запятую.")
        return

    if not item_ids or len(item_ids) > 10:
        await message.answer("❌ Укажите от 1 до 10 предметов.")
        return

    # Проверяем, что предметы принадлежат пользователю и торгуемы
    user = await repos.users.get_by_telegram_id(message.from_user.id)
    owned_items = await repos.items.get_by_owner(user["id"], tradable_only=True)
    owned_ids = {item["id"] for item in owned_items}

    invalid = [i for i in item_ids if i not in owned_ids]
    if invalid:
        await message.answer(
            f"❌ Предметы с ID {invalid} не найдены в вашем инвентаре или не торгуемы."
        )
        return

    await state.update_data(items_offered=item_ids)
    await state.set_state(TradeStates.waiting_items_wanted)
    await message.answer(
        "📝 Шаг 4/4: Опишите, какие скины вы хотите получить\n\n"
        "Например: «AWP | Dragon Lore» или «Скины на сумму до $50»\n"
        "Можно пропустить, отправив «-»."
    )


@router.message(TradeStates.waiting_items_wanted)
async def process_items_wanted(message: Message, state: FSMContext, repos: Repositories) -> None:
    items_wanted = message.text.strip()
    if items_wanted == "-":
        items_wanted = "Не указано"

    data = await state.get_data()
    user = await repos.users.get_by_telegram_id(message.from_user.id)

    offer_id = await repos.offers.create(
        creator_id=user["id"],
        title=data["title"],
        items_offered=data["items_offered"],
        items_wanted=items_wanted,
        description=data.get("description"),
    )

    await state.clear()

    await message.answer(
        f"✅ Предложение обмена создано!\n\n"
        f"ID: #{offer_id}\n"
        f"Название: {data['title']}\n"
        f"Описание: {data.get('description') or '-'}\n"
        f"Предметов отдаёте: {len(data['items_offered'])}\n"
        f"Хотите получить: {items_wanted}\n\n"
        f"Предложение опубликовано и доступно другим пользователям.",
        reply_markup=back_to_main_keyboard(),
    )