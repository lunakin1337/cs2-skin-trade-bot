"""Inline-клавиатуры."""

import os
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo


def _get_web_app_url() -> str:
    """Получить URL веб-приложения из переменной окружения или использовать дефолт."""
    return os.getenv("WEB_APP_URL", "http://localhost:8080")


def main_menu_keyboard() -> InlineKeyboardMarkup:
    web_app_url = _get_web_app_url()
    
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
            [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="inventory")],
            [InlineKeyboardButton(text="📋 Предложения", callback_data="offers")],
            [InlineKeyboardButton(text="🔄 Мои сделки", callback_data="trades")],
            [InlineKeyboardButton(text="🌐 Открыть приложение", web_app=WebAppInfo(url=web_app_url))],
            [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
        ]
    )


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu")]
        ]
    )


def inventory_keyboard(has_steam: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура для инвентаря."""
    buttons = []
    if has_steam:
        buttons.append([InlineKeyboardButton(text="🔄 Синхронизировать с Steam", callback_data="sync_inventory")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)