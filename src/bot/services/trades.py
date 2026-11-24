"""Обмены: ссылки Steam Trade с предзаполненными скинами и детали сделки."""

import json
from urllib.parse import quote

from database.repository import Repositories

STEAM_TRADE_BASE = "https://steamcommunity.com/tradeoffer/new/"
CS2_APP_ID = 730
CS2_CONTEXT_ID = 2


def steam_trade_link(partner: str | None, token: str | None, asset_ids: list[str]) -> str | None:
    """Ссылка на обмен, где уже подставлены скины отправителя.

    Steam принимает параметр items — массив предметов отправителя, поэтому
    человек открывает ссылку и сразу видит готовый трейд.
    """
    if not partner or not token:
        return None

    url = f"{STEAM_TRADE_BASE}?partner={partner}&token={token}"
    if not asset_ids:
        return url

    items = [
        {"appid": CS2_APP_ID, "contextid": CS2_CONTEXT_ID, "amount": 1, "assetid": str(asset_id)}
        for asset_id in asset_ids
    ]
    payload = json.dumps(items, separators=(",", ":"))
    return f"{url}&items={quote(payload, safe='')}"


async def trade_sides(repos: Repositories, trade: dict) -> dict:
    """Что каждая сторона отдаёт: названия и steam asset id."""
    links = await repos.trade_items.get_by_trade(trade["id"])
    item_ids = [link["item_id"] for link in links]
    items = {item["id"]: item for item in await repos.items.get_by_ids(item_ids)}

    sides = {"buyer": [], "seller": []}
    for link in links:
        item = items.get(link["item_id"])
        if not item:
            continue
        entry = {
            "name": item.get("market_hash_name") or "—",
            "asset_id": str(item.get("steam_asset_id") or ""),
            "price": item.get("price_steam"),
            "image": item.get("image_url"),
        }
        role = "buyer" if link["from_user_id"] == trade["buyer_id"] else "seller"
        sides[role].append(entry)

    return sides


async def trade_payload(repos: Repositories, trade: dict, viewer_id: int) -> dict:
    """Всё, что нужно интерфейсу по одной сделке с точки зрения пользователя."""
    sides = await trade_sides(repos, trade)
    role = "buyer" if trade["buyer_id"] == viewer_id else "seller"
    counterpart_role = "seller" if role == "buyer" else "buyer"

    counterpart_id = trade["seller_id"] if role == "buyer" else trade["buyer_id"]
    counterpart = await repos.users.get_by_id(counterpart_id)

    partner = (counterpart or {}).get("steam_trade_partner")
    token = (counterpart or {}).get("steam_trade_token")
    my_assets = [item["asset_id"] for item in sides[role] if item["asset_id"]]

    # ссылка на обмен появляется только когда подтвердили обе стороны
    ready = trade["status"] == "in_escrow"

    return {
        "role": role,
        "direction": "incoming" if role == "seller" else "outgoing",
        "my_items": sides[role],
        "their_items": sides[counterpart_role],
        "steam_url": steam_trade_link(partner, token, my_assets) if ready else None,
        "counterpart": (counterpart or {}).get("username") or (counterpart or {}).get("first_name") or "—",
        "counterpart_telegram": (counterpart or {}).get("telegram_id"),
        "dispute_open": await repos.disputes.get_open_by_trade(trade["id"]) is not None,
    }
