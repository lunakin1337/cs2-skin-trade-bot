"""Форматирование текстов для сообщений бота."""

from urllib.parse import quote

from bot.utils.steam import TradeUrl, build_image_url

MARKET_LISTINGS_URL = "https://steamcommunity.com/market/listings/730/"


def format_price(price: float | None) -> str:
    """Цена в USD или прочерк."""
    if price is None:
        return "—"
    return f"${price:,.2f}"


def market_url(market_hash_name: str | None) -> str | None:
    if not market_hash_name:
        return None
    return f"{MARKET_LISTINGS_URL}{quote(market_hash_name)}"


def format_user_profile(user: dict) -> str:
    steam_linked = bool(user.get("is_steam_linked"))
    persona = user.get("steam_persona")
    steam_id = user.get("steam_id")

    lines = [
        "👤 <b>Профиль</b>",
        "",
        f"ID: <code>{user['telegram_id']}</code>",
        f"Имя: {user.get('first_name') or '—'} {user.get('last_name') or ''}".rstrip(),
        f"Username: @{user.get('username') or '—'}",
        f"Статус: {'🔴 Забанен' if user.get('is_banned') else '🟢 Активен'}",
        f"Рейтинг: {user.get('rating') or 0:.1f} ⭐ · сделок: {user.get('trades_count') or 0}",
        "",
        "<b>Steam</b>",
    ]

    if not steam_linked or not steam_id:
        lines.append("❌ Не привязан — нажмите «Привязать Steam»")
        return "\n".join(lines)

    if persona:
        lines.append(f"Аккаунт: {persona}")
    lines.append(f"SteamID64: <code>{steam_id}</code>")

    profile_url = user.get("steam_profile_url") or f"https://steamcommunity.com/profiles/{steam_id}"
    lines.append(f'Ссылка: <a href="{profile_url}">профиль Steam</a>')

    trade_url = _trade_url_hint(user)
    lines.append(f"Trade URL: {trade_url}")

    if user.get("inventory_synced_at"):
        lines.append(f"Инвентарь обновлён: {user['inventory_synced_at']} UTC")

    return "\n".join(lines)


def _trade_url_hint(user: dict) -> str:
    partner = user.get("steam_trade_partner")
    token = user.get("steam_trade_token")
    if partner and token:
        return TradeUrl(partner=str(partner), token=str(token)).masked
    if user.get("steam_trade_url"):
        return "✅ указан"
    return "❌ не указан"


def format_item(item: dict, index: int | None = None) -> str:
    """Карточка предмета в одну-две строки."""
    name = item.get("market_hash_name") or item.get("item_name") or "Неизвестный предмет"
    prefix = f"<code>{index}</code>. " if index is not None else ""
    details = []

    if item.get("rarity"):
        details.append(item["rarity"])
    if item.get("exterior"):
        details.append(item["exterior"])
    if item.get("float_value") is not None:
        details.append(f"float {item['float_value']:.4f}")

    suffix = f"\n     {' · '.join(details)}" if details else ""
    price = f"\n     {format_price(item.get('price_steam'))}"
    tradable = "" if item.get("is_tradable") else " 🔒"

    return f"{prefix}{name}{tradable}{suffix}{price}"


def format_offer(offer: dict) -> str:
    return (
        f"<b>#{offer['id']} · {offer['title']}</b>\n"
        f"   Продавец: @{offer.get('username') or '—'}"
        f" · рейтинг {offer.get('rating') or 0:.1f} ⭐\n"
        f"   Хочет: {offer.get('items_wanted') or '—'}"
    )


def format_item_photo_caption(item: dict) -> str:
    """Подпись к фото предмета (лимит Telegram — 1024 символа)."""
    name = item.get("market_hash_name") or item.get("item_name") or "Неизвестный предмет"
    parts = [f"<b>{name}</b>"]
    if item.get("price_steam"):
        parts.append(format_price(item["price_steam"]))
    if not item.get("is_tradable"):
        parts.append("🔒 не торгуется")
    return " · ".join(parts)[:1000]


def item_image_url(item: dict) -> str | None:
    """Полный URL картинки предмета из сохранённых полей."""
    if item.get("image_url"):
        return item["image_url"]
    return build_image_url(item.get("icon_url"))


TRADE_STATUS_LABELS = {
    "pending": "⏳ ждёт подтверждения сторон",
    "confirmed": "✅ подтверждена",
    "in_escrow": "🔒 готово к обмену в Steam",
    "completed": "🏁 завершена",
    "cancelled": "❌ отменена",
    "disputed": "⚖️ спор",
}


def trade_role(trade: dict, viewer_id: int) -> str:
    """Роль пользователя в сделке: buyer или seller."""
    return "buyer" if trade["buyer_id"] == viewer_id else "seller"


def trade_counterpart_url(trade: dict, viewer_id: int) -> str | None:
    """Trade URL контрагента — по нему открывается Steam-обмен."""
    return trade.get("seller_trade_url" if trade_role(trade, viewer_id) == "buyer" else "buyer_trade_url")


def format_trade(trade: dict, viewer_id: int) -> str:
    role = trade_role(trade, viewer_id)
    is_buyer = role == "buyer"
    counterpart = (trade.get("seller_username") if is_buyer else trade.get("buyer_username")) or "—"
    status = TRADE_STATUS_LABELS.get(trade["status"], trade["status"])

    confirmations = []
    for side, title in (("buyer", "покупатель"), ("seller", "продавец")):
        mark = "✅" if trade.get(f"{side}_confirmed_at") else "⏳"
        confirmations.append(f"{title} {mark}")

    lines = [
        f"<b>#{trade['id']}</b> · {status}",
        f"   Вы {'покупатель' if is_buyer else 'продавец'} · контрагент @{counterpart}",
        f"   Подтверждения: {', '.join(confirmations)}",
    ]
    if trade["status"] in {"in_escrow", "completed"}:
        received = "✅" if trade.get(f"{role}_completed_at") else "⏳"
        lines.append(f"   Скины получены: {received}")
    return "\n".join(lines)
