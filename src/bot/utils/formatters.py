"""Форматирование текстов для сообщений бота."""

import re
from urllib.parse import quote

from bot.utils.steam import TradeUrl, build_image_url

MARKET_LISTINGS_URL = "https://steamcommunity.com/market/listings/730/"
NEWLINE = chr(10)

WEAR_ABBR = {
    "factory new": "FN",
    "minimal wear": "MW",
    "field-tested": "FT",
    "well-worn": "WW",
    "battle-scarred": "BS",
    "прямо с завода": "FN",
    "немного поношенное": "MW",
    "после полевых испытаний": "FT",
    "поношенное": "WW",
    "закалённое в боях": "BS",
    "закаленное в боях": "BS",
}


def wear_abbr(value) -> str:
    """Износ как в Steam: FN / MW / FT / WW / BS."""
    if not value:
        return "—"
    return WEAR_ABBR.get(str(value).strip().lower(), str(value))


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


def short_name(market_hash_name: str | None, limit: int = 32) -> str:
    """Название без износа в скобках — для заголовков предложений."""
    if not market_hash_name:
        return "—"
    name = re.sub(r"\s*\([^)]*\)\s*$", "", market_hash_name).strip()
    return name[:limit]


def format_item(item: dict, index: int | None = None) -> str:
    """Карточка предмета в одну-две строки."""
    name = item.get("market_hash_name") or item.get("item_name") or "Неизвестный предмет"
    prefix = f"<code>{index}</code>. " if index is not None else ""
    details = []

    if item.get("rarity"):
        details.append(item["rarity"])
    if item.get("exterior"):
        details.append(wear_abbr(item["exterior"]))
    if item.get("float_value") is not None:
        details.append(f"float {item['float_value']:.4f}")

    suffix = f"\n     {' · '.join(details)}" if details else ""
    price = f"\n     {format_price(item.get('price_steam'))}"
    tradable = " 🔒" if item.get("is_tradable") == 0 else ""

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

    my_items = trade.get("my_items") or []
    their_items = trade.get("their_items") or []
    if my_items:
        names = ", ".join(short_name(item["name"], 26) for item in my_items[:3])
        lines.append(f"   Отдаёте: {names}")
    if their_items:
        names = ", ".join(short_name(item["name"], 26) for item in their_items[:3])
        lines.append(f"   Получаете: {names}")

    return "\n".join(lines)


CARD_COLUMN = 18
CARD_INNER = CARD_COLUMN * 2 + 1


def _wrap(text: str, width: int) -> list[str]:
    words = str(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return [line[:width] for line in lines] or [""]


def _pad(text: str, width: int) -> str:
    text = str(text)[:width]
    return text + " " * (width - len(text))


def format_author(offer: dict) -> str:
    """Автор объявления: @username, иначе имя, иначе telegram id."""
    if offer.get("username"):
        return f"@{offer['username']}"
    if offer.get("first_name"):
        return str(offer["first_name"])
    if offer.get("telegram_id"):
        return f"id {offer['telegram_id']}"
    return "—"


def format_offer_card(offer: dict, offered_items: list, index: int) -> str:
    """Карточка предложения: слева что отдаёт, справа что хочет, снизу комментарий."""
    left: list[str] = []
    for item in offered_items[:3]:
        left.extend(_wrap(item.get("market_hash_name") or "—", CARD_COLUMN))
    if len(offered_items) > 3:
        left.append(f"+{len(offered_items) - 3} ещё")

    total = sum(float(item.get("price_steam") or 0) for item in offered_items)
    if total:
        left.append(format_price(total))

    if offer.get("description"):
        left.extend(_wrap(offer["description"], CARD_COLUMN))

    wanted = offer.get("wanted_name") or offer.get("items_wanted") or "—"
    right = _wrap(wanted, CARD_COLUMN)

    height = max(len(left), len(right))
    left += [""] * (height - len(left))
    right += [""] * (height - len(right))

    user = format_author(offer)
    rating = f"{float(offer.get('rating') or 0):.1f}⭐"
    footer = _wrap(f"#{offer['id']} · {user} · {rating}", CARD_INNER)

    frame_top = "┌" + "─" * CARD_COLUMN + "┬" + "─" * CARD_COLUMN + "┐"
    frame_mid = "├" + "─" * CARD_COLUMN + "┼" + "─" * CARD_COLUMN + "┤"
    frame_split = "├" + "─" * CARD_INNER + "┤"
    frame_bottom = "└" + "─" * CARD_INNER + "┘"

    rows = [
        frame_top,
        f"│{_pad('ОТДАЮ', CARD_COLUMN)}│{_pad('ХОЧУ', CARD_COLUMN)}│",
        frame_mid,
    ]
    rows.extend(
        f"│{_pad(left_line, CARD_COLUMN)}│{_pad(right_line, CARD_COLUMN)}│"
        for left_line, right_line in zip(left, right)
    )
    rows.append(frame_split)
    rows.extend(f"│{_pad(line, CARD_INNER)}│" for line in footer)
    rows.append(frame_bottom)
    return NEWLINE.join(rows)
