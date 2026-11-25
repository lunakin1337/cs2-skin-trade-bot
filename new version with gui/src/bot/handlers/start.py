"""Команды /start, /help, /menu и главное меню."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import back_to_main_keyboard, main_menu_keyboard
from bot.utils.telegram import edit_or_send, notify
from bot.utils.users import ensure_user
from config.settings import BotConfig
from database.repository import Repositories

router = Router()

WELCOME_TEXT = (
    "👋 <b>Добро пожаловать в P2P обмен скинами CS2!</b>\n\n"
    "1. Привяжите Steam аккаунт и Trade URL в профиле\n"
    "2. Синхронизируйте инвентарь — подтянем скины и цены\n"
    "3. Создавайте предложения обмена или принимайте чужие\n\n"
    "Команды: /board · /create_offer · /my_offers · /trades"
)

MENU_TEXT = (
    "🏠 <b>Главное меню</b>\n\n"
    "Профиль — Steam аккаунт и Trade URL\n"
    "Инвентарь — скины с ценами и картинками\n"
    "Предложения — что предлагают другие\n"
    "Сделки — ваши обмены и подтверждения"
)

HELP_TEXT = (
    "📖 <b>Справка</b>\n\n"
    "<b>Профиль</b>\n"
    "/profile — профиль, привязка Steam и Trade URL\n\n"
    "<b>Инвентарь</b>\n"
    "/inventory — скины, цены и картинки из Steam\n\n"
    "<b>Обмен</b>\n"
    "/offers — публичные предложения\n"
    "/create_offer — создать своё предложение\n"
    "/trades — сделки и подтверждения\n"
    "/trade — как проходит обмен\n\n"
    "<b>Прочее</b>\n"
    "/rating — ваш рейтинг и отзывы\n"
    "/escrow — как работает эскроу\n"
    "/dispute — открыть спор по сделке\n"
    "/help — эта справка"
)


@router.message(CommandStart())
async def cmd_start(message: Message, repos: Repositories, config: BotConfig) -> None:
    await ensure_user(repos, message.from_user)
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard(config.web_app_url))


@router.message(Command("menu"))
async def cmd_menu(message: Message, config: BotConfig) -> None:
    await message.answer(MENU_TEXT, reply_markup=main_menu_keyboard(config.web_app_url))


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    await state.clear()
    await edit_or_send(callback.message, MENU_TEXT, main_menu_keyboard(config.web_app_url))
    await notify(callback)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=back_to_main_keyboard())


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery) -> None:
    await edit_or_send(callback.message, HELP_TEXT, back_to_main_keyboard())
    await notify(callback)
