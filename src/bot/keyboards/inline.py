"""Inline-клавиатуры бота."""

from typing import Iterable, Optional

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)

from bot.services.disputes import DISPUTE_STATUSES

ACTIVE_TRADE_STATUSES = {"pending", "confirmed", "in_escrow"}


def main_menu_keyboard(web_app_url: Optional[str] = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
            InlineKeyboardButton(text="🎒 Инвентарь", callback_data="inventory"),
        ],
        [
            InlineKeyboardButton(text="📝 Создать предложение", callback_data="create_offer"),
            InlineKeyboardButton(text="📂 Мои предложения", callback_data="my_offers"),
        ],
        [InlineKeyboardButton(text="📋 Доска", callback_data="board")],
        [InlineKeyboardButton(text="🔄 История сделок", callback_data="trades")],
    ]

    last_row = []
    if web_app_url and web_app_url.startswith("https://"):
        last_row.append(
            InlineKeyboardButton(text="🌐 Приложение", web_app=WebAppInfo(url=web_app_url))
        )
    last_row.append(InlineKeyboardButton(text="❓ Помощь", callback_data="help"))
    rows.append(last_row)

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


def board_keyboard(
    offers: Iterable[dict],
    page: int,
    pages: int,
    viewer_telegram_id: int | None = None,
) -> InlineKeyboardMarkup:
    offers = list(offers)
    rows: list[list[InlineKeyboardButton]] = []

    accept = [
        InlineKeyboardButton(text=f"🤝 Принять #{offer['id']}", callback_data=f"accept_offer_{offer['id']}")
        for offer in offers
        if viewer_telegram_id is None or offer.get("telegram_id") != viewer_telegram_id
    ]
    for index in range(0, len(accept), 2):
        rows.append(accept[index:index + 2])

    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="◀️", callback_data=f"board_{page - 1}"))
    if pages > 1:
        navigation.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="board_noop"))
    if page + 1 < pages:
        navigation.append(InlineKeyboardButton(text="▶️", callback_data=f"board_{page + 1}"))
    if navigation:
        rows.append(navigation)

    rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_offers_keyboard(offers: Iterable[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for offer in offers:
        offer_id = offer["id"]
        if offer.get("status") == "active":
            rows.append(
                [
                    InlineKeyboardButton(text=f"⏸ Снять #{offer_id}", callback_data=f"offer_cancel_{offer_id}"),
                    InlineKeyboardButton(text=f"🗑 Удалить #{offer_id}", callback_data=f"offer_delete_{offer_id}"),
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(text=f"🗑 Удалить #{offer_id}", callback_data=f"offer_delete_{offer_id}"),
                ]
            )
    rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def offers_keyboard(offers: Iterable[dict]) -> InlineKeyboardMarkup:
    """Кнопки для списка предложений без карточек (совместимость)."""
    return board_keyboard(offers, page=0, pages=1)


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
            steam_url = trade.get("steam_url")
            if steam_url:
                rows.append(
                    [InlineKeyboardButton(text=f"🔗 Steam Trade #{trade_id}", url=steam_url)]
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

        if status in DISPUTE_STATUSES and not trade.get("dispute_open"):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"⚠️ Открыть спор #{trade_id}",
                        callback_data=f"trade_dispute_{trade_id}",
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


def draft_keyboard(has_candidates: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data="draft_publish")],
        [InlineKeyboardButton(text="🔁 Другой вариант", callback_data="draft_retry")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="draft_cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rating_keyboard(trade_id: int) -> InlineKeyboardMarkup:
    scores = [
        InlineKeyboardButton(text=f"{score}⭐", callback_data=f"rate_{trade_id}_{score}")
        for score in range(1, 6)
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[scores, [InlineKeyboardButton(text="◀️ К сделкам", callback_data="trades")]]
    )
