"""Профиль пользователя и привязка Steam."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import back_to_main_keyboard, profile_keyboard
from bot.states.trade import ProfileStates
from bot.utils.formatters import format_user_profile
from bot.utils.steam import (
    SteamClient,
    SteamError,
    SteamProfile,
    get_steam_client,
    parse_trade_url,
)
from bot.utils.telegram import edit_or_send, notify
from bot.utils.validators import validate_steam_id64, validate_trade_url
from config.settings import BotConfig
from bot.utils.users import ensure_user
from database.repository import Repositories

logger = logging.getLogger(__name__)

router = Router()

STEAM_ID_PROMPT = (
    "🔗 <b>Привязка Steam</b>\n\n"
    "Шаг 1/2: отправьте SteamID64 — 17 цифр, например <code>76561198000000000</code>.\n\n"
    "Найти свой ID можно на steamid.io или в ссылке на профиль."
)

TRADE_URL_PROMPT = (
    "🔗 Шаг 2/2: отправьте Steam Trade URL.\n\n"
    "Он выглядит так:\n"
    "<code>https://steamcommunity.com/tradeoffer/new/?partner=123456&token=ABCDEF</code>\n\n"
    "Где взять: Инвентарь → «Обмен» → «Кто может отправлять мне предложения обмена» → "
    "«Публичная ссылка на обмен»."
)


async def fetch_steam_profile(config: BotConfig, steam_id: str) -> tuple[SteamProfile | None, str | None]:
    """Публичный профиль Steam: (профиль, причина отсутствия)."""
    if not config.has_steam_api_key:
        return None, "STEAM_API_KEY не задан — имя и аватар Steam недоступны"

    client: SteamClient = get_steam_client(config.steam_api_key)
    try:
        profile = await client.fetch_profile(steam_id)
    except SteamError as error:
        logger.warning("Не удалось получить профиль Steam %s: %s", steam_id, error)
        return None, str(error)

    if profile is None:
        return None, "Профиль Steam не найден"
    return profile, None


@router.message(Command("profile"))
async def cmd_profile(message: Message, repos: Repositories, config: BotConfig) -> None:
    user = await ensure_user(repos, message.from_user)
    text = format_user_profile(user)
    markup = profile_keyboard(user)

    if user.get("steam_avatar_url"):
        await message.answer_photo(user["steam_avatar_url"], caption=text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery, repos: Repositories, config: BotConfig) -> None:
    user = await ensure_user(repos, callback.from_user)
    await edit_or_send(callback.message, format_user_profile(user), profile_keyboard(user))
    await notify(callback)


@router.callback_query(F.data == "steam_refresh")
async def cb_steam_refresh(callback: CallbackQuery, repos: Repositories, config: BotConfig) -> None:
    user = await ensure_user(repos, callback.from_user)
    if not user.get("is_steam_linked") or not user.get("steam_id"):
        await notify(callback, "Steam ещё не привязан", alert=True)
        return

    profile, error = await fetch_steam_profile(config, user["steam_id"])
    if profile is None:
        await notify(callback, error or "Не удалось обновить профиль", alert=True)
        return

    await repos.users.set_steam_profile(
        user["id"],
        persona_name=profile.persona_name,
        avatar_url=profile.avatar_url,
        profile_url=profile.profile_url,
    )
    user = await repos.users.get_by_id(user["id"])
    await edit_or_send(callback.message, format_user_profile(user), profile_keyboard(user))
    await notify(callback, "Профиль Steam обновлён")


@router.callback_query(F.data == "link_steam")
async def cb_link_steam(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileStates.waiting_steam_id)
    await edit_or_send(callback.message, STEAM_ID_PROMPT, back_to_main_keyboard())
    await notify(callback)


@router.message(ProfileStates.waiting_steam_id)
async def process_steam_id(message: Message, state: FSMContext, config: BotConfig) -> None:
    steam_id = (message.text or "").strip()
    is_valid, error = validate_steam_id64(steam_id)
    if not is_valid:
        await message.answer(f"❌ {error}\nПопробуйте снова.", reply_markup=back_to_main_keyboard())
        return

    profile, profile_error = await fetch_steam_profile(config, steam_id)
    await state.update_data(
        steam_id=steam_id,
        persona_name=profile.persona_name if profile else None,
        avatar_url=profile.avatar_url if profile else None,
        profile_url=profile.profile_url if profile else None,
    )
    await state.set_state(ProfileStates.waiting_trade_url)

    note = ""
    if profile:
        note = f"✅ Найден аккаунт: <b>{profile.persona_name}</b>\n\n"
    elif profile_error:
        note = f"⚠️ {profile_error}\n\n"

    await message.answer(note + TRADE_URL_PROMPT, reply_markup=back_to_main_keyboard())


@router.message(ProfileStates.waiting_trade_url)
async def process_trade_url(message: Message, state: FSMContext, repos: Repositories) -> None:
    trade_url = (message.text or "").strip()
    is_valid, error = validate_trade_url(trade_url)
    if not is_valid:
        await message.answer(f"❌ {error}\nПопробуйте снова.", reply_markup=back_to_main_keyboard())
        return

    parsed = parse_trade_url(trade_url)
    data = await state.get_data()
    steam_id = data.get("steam_id")

    if not steam_id or not parsed:
        await state.clear()
        await message.answer(
            "❌ Сессия привязки истекла, начните заново из профиля.",
            reply_markup=back_to_main_keyboard(),
        )
        return

    user = await ensure_user(repos, message.from_user)
    await repos.users.link_steam(
        user["id"],
        steam_id,
        parsed.url,
        trade_partner=parsed.partner,
        trade_token=parsed.token,
        persona_name=data.get("persona_name"),
        avatar_url=data.get("avatar_url"),
        profile_url=data.get("profile_url"),
    )
    await state.clear()

    user = await repos.users.get_by_id(user["id"])
    await message.answer(
        "✅ Steam привязан!\n\n"
        f"SteamID64: <code>{steam_id}</code>\n"
        f"Trade URL: {parsed.masked}\n\n"
        "Осталось синхронизировать инвентарь — нажмите «🔄 Синхронизировать» в разделе инвентаря.",
        reply_markup=profile_keyboard(user),
    )
