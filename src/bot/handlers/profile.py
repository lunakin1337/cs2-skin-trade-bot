"""Хендеры профиля и привязки Steam."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.states.trade import ProfileStates
from database.repository import Repositories
from bot.keyboards.inline import back_to_main_keyboard
from bot.utils.validators import validate_steam_id64, validate_trade_url

router = Router()


@router.message(Command("profile"))
async def cmd_profile(message: Message, repos: Repositories) -> None:
    user = await repos.users.get_by_telegram_id(message.from_user.id)
    if not user:
        await repos.users.create_or_update(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        user = await repos.users.get_by_telegram_id(message.from_user.id)

    steam_status = "✅ Привязан" if user.get("is_steam_linked") else "❌ Не привязан"
    ban_status = "🔴 Забанен" if user.get("is_banned") else "🟢 Активен"

    await message.answer(
        "👤 <b>Профиль</b>\n\n"
        f"ID: <code>{user['telegram_id']}</code>\n"
        f"Имя: {user.get('first_name') or '-'} {user.get('last_name') or '-'}\n"
        f"Username: @{user.get('username') or '-'}\n"
        f"Steam: {steam_status}\n"
        f"Статус: {ban_status}\n"
        f"Рейтинг: {user.get('rating', 0):.1f} ⭐\n"
        f"Сделок: {user.get('trades_count', 0)}\n\n"
        f"Steam ID: {user.get('steam_id', '-')}\n"
        f"Trade URL: {user.get('steam_trade_url', '-')}",
        reply_markup=back_to_main_keyboard(),
    )


@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery, repos: Repositories) -> None:
    user = await repos.users.get_by_telegram_id(callback.from_user.id)
    if not user:
        await repos.users.create_or_update(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
        )
        user = await repos.users.get_by_telegram_id(callback.from_user.id)

    steam_status = "✅ Привязан" if user.get("is_steam_linked") else "❌ Не привязан"
    ban_status = "🔴 Забанен" if user.get("is_banned") else "🟢 Активен"

    await callback.message.edit_text(
        "👤 <b>Профиль</b>\n\n"
        f"ID: <code>{user['telegram_id']}</code>\n"
        f"Имя: {user.get('first_name') or '-'} {user.get('last_name') or '-'}\n"
        f"Username: @{user.get('username') or '-'}\n"
        f"Steam: {steam_status}\n"
        f"Статус: {ban_status}\n"
        f"Рейтинг: {user.get('rating', 0):.1f} ⭐\n"
        f"Сделок: {user.get('trades_count', 0)}\n\n"
        f"Steam ID: {user.get('steam_id', '-')}\n"
        f"Trade URL: {user.get('steam_trade_url', '-')}",
        reply_markup=back_to_main_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "link_steam")
async def cb_link_steam(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileStates.waiting_steam_id)
    await callback.message.edit_text(
        "🔗 <b>Привязка Steam аккаунта</b>\n\n"
        "Введите ваш SteamID64 (17-значный номер, например: 76561198000000000)\n\n"
        "Узнать свой SteamID64 можно на сайте steamid.io",
        reply_markup=back_to_main_keyboard(),
    )
    await callback.answer()


@router.message(ProfileStates.waiting_steam_id)
async def process_steam_id(message: Message, state: FSMContext, repos: Repositories) -> None:
    steam_id = message.text.strip()

    is_valid, error = validate_steam_id64(steam_id)
    if not is_valid:
        await message.answer(
            f"❌ {error}\nПопробуйте снова или нажмите «Назад в меню».",
            reply_markup=back_to_main_keyboard(),
        )
        return

    await state.update_data(steam_id=steam_id)
    await state.set_state(ProfileStates.waiting_trade_url)
    await message.answer(
        "🔗 Теперь введите ваш Steam Trade URL\n\n"
        "Пример: https://steamcommunity.com/tradeoffer/new/?partner=123456&token=ABCDEF\n\n"
        "Как получить: Профиль → Инвентарь → Предложения обмене → «Кто может отправить мне предложения обмене?» → «Третьи лица» → скопируйте ссылку",
        reply_markup=back_to_main_keyboard(),
    )


@router.message(ProfileStates.waiting_trade_url)
async def process_trade_url(message: Message, state: FSMContext, repos: Repositories) -> None:
    trade_url = message.text.strip()

    is_valid, error = validate_trade_url(trade_url)
    if not is_valid:
        await message.answer(
            f"❌ {error}\nПопробуйте снова.",
            reply_markup=back_to_main_keyboard(),
        )
        return

    data = await state.get_data()
    steam_id = data.get("steam_id")

    user = await repos.users.get_by_telegram_id(message.from_user.id)
    if not user:
        await repos.users.create_or_update(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        user = await repos.users.get_by_telegram_id(message.from_user.id)

    await repos.users.link_steam(user["id"], steam_id, trade_url)
    await state.clear()

    await message.answer(
        "✅ Steam аккаунт успешно привязан!\n\n"
        f"Steam ID: <code>{steam_id}</code>\n"
        f"Trade URL: {trade_url}\n\n"
        "Теперь вы можете просматривать инвентарь и создавать предложения обмене.",
        reply_markup=back_to_main_keyboard(),
    )