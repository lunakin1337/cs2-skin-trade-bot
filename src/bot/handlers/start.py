"""Хендеры команд /start и /help."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command

from database.repository import Repositories

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, repos: Repositories) -> None:
    await repos.users.create_or_update(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )

    await message.answer(
        "👋 Добро пожаловать в бот P2P обмена скинами CS2!\n\n"
        "Доступные команды:\n"
        "/profile — ваш профиль и Steam аккаунт\n"
        "/inventory — ваш инвентарь скинов\n"
        "/offers — публичные предложения обмена\n"
        "/create_offer — создать предложение обмена\n"
        "/trades — ваши сделки\n"
        "/help — справка\n\n"
        "Начните с привязки Steam аккаунта через /profile.",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "📖 Справка по боту\n\n"
        "/start — запуск бота\n"
        "/profile — профиль и привязка Steam\n"
        "/inventory — инвентарь скинов\n"
        "/offers — список предложений обмена\n"
        "/create_offer — создать предложение\n"
        "/trades — история сделок\n"
        "/help — эта справка\n\n"
        "Поддержка: обращайтесь к администратору.",
    )


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🏠 Главное меню\n\n"
        "Выберите раздел:",
    )
    await callback.answer()