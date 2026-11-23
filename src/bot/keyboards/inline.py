"""Inline-клавиатуры бота."""

from typing import Iterable, Optional

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)

ACTIVE_TRADE_STATUSES = {"pending", "confirmed", "in_escrow"}


def main_menu_keyboard(web_app_url: Optional[str] = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="inventory")],
        [
            InlineKeyboardButton(text="📋 Предложения", callback_data="offers"),
            InlineKeyboardButton(text="🔄 Мои сделки", callback_data="trades"),
        ],
        [InlineKeyboardButton(text="📝 Создать предложение", callback_data="create_offer")],
    ]
    if web_app_url and web_app_url.startswith("https://"):
        rows.append([InlineKeyboardButton(text="🌐 Приложение", web_app=WebAppInfo(url=web_app_url))])
    rows.append([InlineKeyboardButton(text="❓ Помощь", callback_data="help")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")]]
    )


def profile_keyboard(user: dict) -> InlineKeyboardMarkup:
    if user.get("is_steam_linked"):
        rows = [
            [InlineKeyboardButton(text="🔄 Обновить профиль Steam", callback_data="steam_refresh")],
            [InlineKeyboardButton(text="🔗 Изменить Trade URL", callback_data="link_steam")],
            [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="inventory")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="🔗 Привязать Steam", callback_data="link_steam")],
            [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="inventory")],
        ]
    rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inventory_keyboard(has_steam: bool, page: int = 0, pages: int = 1) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="◀️", callback_data=f"inv_page_{page - 1}"))
    if pages > 1:
        navigation.append(
            InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="inv_noop")
        )
    if page + 1 < pages:
        navigation.append(InlineKeyboardButton(text="▶️", callback_data=f"inv_page_{page + 1}"))
    if navigation:
        rows.append(navigation)

    if has_steam:
        rows.append([InlineKeyboardButton(text="🔄 Синхронизировать", callback_data="sync_inventory")])
        rows.append([InlineKeyboardButton(text="🖼 Показать картинками", callback_data="inv_photos")])

    rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def offers_keyboard(offers: Iterable[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"Принять #{offer['id']}", callback_data=f"accept_offer_{offer['id']}")]
        for offer in offers
    ]
    rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def trades_keyboard(trades: Iterable[dict], viewer_id: int) -> InlineKeyboardMarkup:
    """Кнопки действий по сделкам: подтверждение, обмен, получение, отмена, оценка."""
    rows: list[list[InlineKeyboardButton]] = []

    for trade in trades:
        trade_id = trade["id"]
        role = "buyer" if trade["buyer_id"] == viewer_id else "seller"
        status = trade["status"]

        if status == "pending" and not trade.get(f"{role}_confirmed_at"):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"✅ Подтвердить #{trade_id}",
                        callback_data=f"trade_confirm_{trade_id}",
                    )
                ]
            )

        if status == "in_escrow":
            counterpart_url = trade.get(
                "seller_trade_url" if role == "buyer" else "buyer_trade_url"
            )
            if counterpart_url:
                rows.append(
                    [InlineKeyboardButton(text=f"🔗 Обмен #{trade_id}", url=counterpart_url)]
                )
            if not trade.get(f"{role}_completed_at"):
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=f"📦 Получил #{trade_id}",
                            callback_data=f"trade_complete_{trade_id}",
                        )
                    ]
                )

        if status in ACTIVE_TRADE_STATUSES:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"✖️ Отменить #{trade_id}",
                        callback_data=f"trade_cancel_{trade_id}",
                    )
                ]
            )

        if status == "completed":
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"⭐ Оценить #{trade_id}",
                        callback_data=f"rate_menu_{trade_id}",
                    )
                ]
            )

    rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rating_keyboard(trade_id: int) -> InlineKeyboardMarkup:
    scores = [
        InlineKeyboardButton(text=f"{score}⭐", callback_data=f"rate_{trade_id}_{score}")
        for score in range(1, 6)
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[scores, [InlineKeyboardButton(text="◀️ К сделкам", callback_data="trades")]]
    )
