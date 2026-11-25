"""JSON API для Telegram Mini App — полный паритет с ботом."""

import json
import logging
from typing import Any, Awaitable, Callable

from aiogram import Bot
from aiohttp import web

from bot.services import notifications
from bot.services.disputes import (
    DISPUTE_STATUSES as DISPUTE_TRADE_STATUSES,
    DisputeError,
    notify_dispute,
    open_dispute,
)
from bot.services.inventory_sync import sync_inventory
from bot.services.skin_search import find_candidates
from bot.services.trades import finalize_due, settle_after_receipt, trade_payload
from bot.utils.formatters import (
    PROTECTION_NOTE,
    TRADE_STATUS_LABELS,
    format_author,
    format_deadline,
    short_name,
    wear_abbr,
)
from bot.utils.skin_categories import CATEGORY_ORDER, category_title, rarity_slug
from bot.utils.steam import TradeUrl, get_steam_client, SteamError, parse_trade_url
from bot.utils.telegram_auth import parse_init_data
from bot.utils.validators import validate_steam_id64, validate_trade_url
from catalog_cache import catalog_version, etag_matches
from config.settings import BotConfig
from database.repository import WEAR_NAMES, Repositories
from webapp_context import BOT_KEY, CATALOG_CACHE_KEY, CONFIG_KEY, REPOS_KEY

logger = logging.getLogger(__name__)

SUPER_ADMIN_ID = 8851272459
BOARD_PAGE_SIZE = 5
INVENTORY_PAGE_SIZE = 20


# ---------- авторизация ----------


def _init_data(request: web.Request) -> str:
    return (
        request.headers.get("X-Telegram-Init-Data")
        or request.query.get("initData")
        or ""
    )


def _config(request: web.Request) -> BotConfig:
    return request.app[CONFIG_KEY]


def _repos(request: web.Request) -> Repositories:
    return request.app[REPOS_KEY]


async def _api_user(request: web.Request) -> dict | None:
    parsed = parse_init_data(_init_data(request), _config(request).token)
    if not parsed or not parsed.get("user"):
        return None

    telegram_user = parsed["user"]
    telegram_id = telegram_user.get("id")
    if not telegram_id:
        return None

    return await _repos(request).users.create_or_update(
        telegram_id=int(telegram_id),
        username=telegram_user.get("username"),
        first_name=telegram_user.get("first_name"),
        last_name=telegram_user.get("last_name"),
    )


def _unauthorized() -> web.Response:
    return web.json_response({"error": "unauthorized"}, status=401)


async def _admin(request: web.Request) -> tuple[dict | None, web.Response | None]:
    user = await _api_user(request)
    if user is None:
        return None, _unauthorized()

    config = _config(request)
    telegram_id = user.get("telegram_id")
    if telegram_id != SUPER_ADMIN_ID and not config.is_admin(telegram_id):
        return None, web.json_response({"error": "forbidden"}, status=403)
    return user, None


async def _body(request: web.Request) -> dict[str, Any]:
    try:
        return await request.json()
    except (json.JSONDecodeError, ValueError):
        return {}


# ---------- кэш каталога ----------


async def _cached_json(
    request: web.Request,
    key: str,
    build: Callable[[], Awaitable[dict]],
) -> web.Response:
    """Отдать JSON каталога из кэша или построить заново, всегда с ETag.

    Каталог одинаков для всех пользователей, поэтому ключ кэша не содержит
    initData. Ответ помечен `private`, а `If-None-Match` даёт 304 без тела.
    """
    ttl = max(0, _config(request).web_cache_ttl)
    cache = request.app[CATALOG_CACHE_KEY]
    version = await catalog_version(_repos(request))

    cached = cache.get(key, version, ttl)
    if cached is None:
        body = json.dumps(await build(), ensure_ascii=False).encode("utf-8")
        etag = cache.put(key, version, body)
    else:
        etag, body = cached

    headers = {"ETag": etag, "Cache-Control": f"private, max-age={ttl}"}
    if etag_matches(request.headers.get("If-None-Match"), etag):
        return web.Response(status=304, headers=headers)
    return web.Response(body=body, content_type="application/json", headers=headers)


# ---------- представление данных ----------


def _profile(user: dict, config: BotConfig) -> dict:
    trade_url = None
    if user.get("steam_trade_partner") and user.get("steam_trade_token"):
        trade_url = TradeUrl(
            partner=str(user["steam_trade_partner"]),
            token=str(user["steam_trade_token"]),
        ).masked

    return {
        "telegram_id": user["telegram_id"],
        "username": user.get("username"),
        "first_name": user.get("first_name"),
        "rating": user.get("rating") or 0,
        "trades_count": user.get("trades_count") or 0,
        "is_admin": user.get("telegram_id") == SUPER_ADMIN_ID or config.is_admin(user.get("telegram_id")),
        "steam": {
            "linked": bool(user.get("is_steam_linked")),
            "persona": user.get("steam_persona"),
            "avatar": user.get("steam_avatar_url"),
            "profile_url": user.get("steam_profile_url"),
            "steam_id": user.get("steam_id"),
            "trade_url": trade_url,
            "synced_at": user.get("inventory_synced_at"),
        },
    }


async def _inventory_json(request: web.Request, user: dict, page: int, size: int) -> dict:
    repos = _repos(request)
    total = await repos.items.count_by_owner(user["id"])
    items = await repos.items.get_by_owner(user["id"], limit=size, offset=page * size)

    return {
        "total": total,
        "tradable": await repos.items.count_by_owner(user["id"], tradable_only=True),
        "value": round(await repos.items.sum_price(user["id"]), 2),
        "page": page,
        "size": size,
        "pages": max(1, -(-total // size)),
        "items": [
            {
                "id": item["id"],
                "name": item.get("market_hash_name") or item.get("item_name") or "—",
                "image": item.get("image_url"),
                "price": item.get("price_steam"),
                "tradable": bool(item.get("is_tradable")),
                "rarity": item.get("rarity"),
                "exterior": wear_abbr(item.get("exterior")),
            }
            for item in items
        ],
    }


def _offer_json(
    offer: dict, items: list[dict], viewer_id: int, match_name: str | None = None
) -> dict:
    return {
        "id": offer["id"],
        "title": offer["title"],
        "author": format_author(offer),
        "rating": offer.get("rating") or 0,
        "status": offer["status"],
        "wanted": offer.get("wanted_name") or offer.get("items_wanted"),
        "comment": offer.get("description"),
        "own": offer["creator_id"] == viewer_id,
        "offered": [
            {
                "name": item.get("market_hash_name"),
                "short": short_name(item.get("market_hash_name")),
                "price": item.get("price_steam"),
                "image": item.get("image_url"),
                "rarity": item.get("rarity"),
            }
            for item in items
        ],
        "value": round(sum(float(item.get("price_steam") or 0) for item in items), 2),
        "match": match_name,
    }


async def _offer_items(repos: Repositories, offer: dict) -> list[dict]:
    try:
        item_ids = json.loads(offer.get("items_offered") or "[]")
    except ValueError:
        item_ids = []
    return await repos.items.get_by_ids(item_ids)


# ---------- профиль ----------


async def api_me(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    data = _profile(user, _config(request))
    summary = await _inventory_json(request, user, 0, 1)
    data["inventory"] = {
        "total": summary["total"],
        "tradable": summary["tradable"],
        "value": summary["value"],
        "synced_at": user.get("inventory_synced_at"),
    }
    return web.json_response(data)


async def api_profile_steam(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    body = await _body(request)
    steam_id = str(body.get("steam_id") or "").strip()
    trade_url_raw = str(body.get("trade_url") or "").strip()

    is_valid, error = validate_steam_id64(steam_id)
    if not is_valid:
        return web.json_response({"error": error}, status=400)

    is_valid, error = validate_trade_url(trade_url_raw)
    if not is_valid:
        return web.json_response({"error": error}, status=400)

    parsed = parse_trade_url(trade_url_raw)
    if parsed is None:
        return web.json_response({"error": "Неверный Trade URL"}, status=400)

    persona = avatar = profile_url = None
    config = _config(request)
    if config.has_steam_api_key:
        try:
            profile = await get_steam_client(config.steam_api_key).fetch_profile(steam_id)
            if profile:
                persona, avatar, profile_url = profile.persona_name, profile.avatar_url, profile.profile_url
        except SteamError as error:
            logger.info("Профиль Steam недоступен: %s", error)

    await _repos(request).users.link_steam(
        user["id"],
        steam_id,
        parsed.url,
        trade_partner=parsed.partner,
        trade_token=parsed.token,
        persona_name=persona,
        avatar_url=avatar,
        profile_url=profile_url,
    )
    user = await _repos(request).users.get_by_id(user["id"])
    return web.json_response({"ok": True, "profile": _profile(user, config)})


async def api_profile_refresh(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    if not user.get("steam_id"):
        return web.json_response({"error": "Steam не привязан"}, status=400)

    config = _config(request)
    if not config.has_steam_api_key:
        return web.json_response({"error": "STEAM_API_KEY не задан"}, status=400)

    try:
        profile = await get_steam_client(config.steam_api_key).fetch_profile(user["steam_id"])
    except SteamError as error:
        return web.json_response({"error": str(error)}, status=400)

    if profile:
        await _repos(request).users.set_steam_profile(
            user["id"], profile.persona_name, profile.avatar_url, profile.profile_url
        )

    user = await _repos(request).users.get_by_id(user["id"])
    return web.json_response({"ok": True, "profile": _profile(user, config)})


# ---------- инвентарь ----------


async def api_inventory(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    try:
        page = max(0, int(request.query.get("page", "0")))
    except ValueError:
        page = 0
    try:
        size = min(50, max(1, int(request.query.get("size", str(INVENTORY_PAGE_SIZE)))))
    except ValueError:
        size = INVENTORY_PAGE_SIZE

    return web.json_response(await _inventory_json(request, user, page, size))


async def api_inventory_sync(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    report = await sync_inventory(_repos(request), user, _config(request))
    return web.json_response(report, status=200 if report.get("ok") else 400)


# ---------- каталог и предложения ----------


async def _catalog_search_payload(request: web.Request, query: str) -> dict:
    repos = _repos(request)
    total = await repos.skins.count()
    if len(query) < 2:
        return {"items": [], "total": total}

    found = await find_candidates(repos, query, limit=5)
    rarities = await repos.items.rarity_map([row["market_hash_name"] for row in found])
    return {
        "items": [
            {
                "name": row["market_hash_name"],
                "price": row.get("price_text"),
                "rarity": rarity_slug(row.get("rarity") or rarities.get(row["market_hash_name"]), row["market_hash_name"]),
            }
            for row in found
        ],
        "total": total,
    }


async def api_catalog(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    query = request.query.get("q", "").strip()
    return await _cached_json(
        request, f"catalog:{query}", lambda: _catalog_search_payload(request, query)
    )


async def _catalog_tree_payload(request: web.Request) -> dict:
    repos = _repos(request)
    tree = await repos.skins.category_tree()
    order = {code: index for index, code in enumerate(CATEGORY_ORDER)}

    categories = [
        {
            "code": row["category"] or "other",
            "title": category_title(row["category"] or "other"),
            "count": row["cnt"],
            "weapons": row["weapons"],
        }
        for row in sorted(tree, key=lambda row: order.get(row["category"], 99))
    ]
    return {"total": await repos.skins.count(), "categories": categories}


async def api_catalog_tree(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    return await _cached_json(request, "catalog:tree", lambda: _catalog_tree_payload(request))


async def _catalog_items_payload(
    request: web.Request,
    category: str | None,
    weapon: str | None,
    query: str | None,
    page: int,
    size: int,
    filters: dict | None = None,
) -> dict:
    repos = _repos(request)
    filters = filters or {}
    # сортировка влияет только на порядок, счётчику она не нужна
    count_filters = {key: value for key, value in filters.items() if key != "sort"}
    total = await repos.skins.count_items(category=category, weapon=weapon, query=query, **count_filters)
    items = await repos.skins.list_items(
        category=category, weapon=weapon, query=query, limit=size, offset=page * size, **filters
    )
    rarities = await repos.items.rarity_map([item["market_hash_name"] for item in items])

    return {
        "total": total,
        "page": page,
        "size": size,
        "pages": max(1, -(-total // size)),
        "items": [
            {
                "name": item["market_hash_name"],
                "short": short_name(item["market_hash_name"]),
                "price": item.get("price_text"),
                "image": item.get("icon_url"),
                "category": item.get("category"),
                "weapon": item.get("weapon"),
                "rarity": rarity_slug(item.get("rarity") or rarities.get(item["market_hash_name"]), item["market_hash_name"]),
            }
            for item in items
        ],
    }


CATALOG_SORTS = ("price_asc", "price_desc", "name", "new")


def _catalog_price(request: web.Request, name: str) -> float | None:
    raw = (request.query.get(name) or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return max(0.0, min(value, 100000.0))


def _catalog_filters(request: web.Request) -> dict:
    """Фильтры каталога из query: сортировка, износ, цена, StatTrak."""
    sort = (request.query.get("sort") or "price_asc").strip()
    wear = (request.query.get("wear") or "").strip().lower()
    return {
        "sort": sort if sort in CATALOG_SORTS else "price_asc",
        "wear": wear if wear in WEAR_NAMES else None,
        "min_price": _catalog_price(request, "min"),
        "max_price": _catalog_price(request, "max"),
        "stattrak": (request.query.get("st") or "") in ("1", "true", "on"),
    }


async def _available_tree_payload(request: web.Request) -> dict:
    total, categories = await _repos(request).skins.available_tree()
    return {
        "total": total,
        "categories": [
            {
                "code": category["code"],
                "title": category_title(category["code"]),
                "count": category["count"],
                "weapons": category["weapons"],
            }
            for category in categories
        ],
    }


async def api_catalog_available_tree(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()
    return await _cached_json(request, "catalog:available:tree", lambda: _available_tree_payload(request))


async def _available_items_payload(
    request: web.Request, category: str | None, weapon: str | None, query: str | None, page: int, size: int
) -> dict:
    repos = _repos(request)
    total = await repos.skins.count_available(category=category, weapon=weapon, query=query)
    items = await repos.skins.available_items(
        category=category, weapon=weapon, query=query, limit=size, offset=page * size
    )
    return {
        "total": total,
        "page": page,
        "size": size,
        "pages": max(1, -(-total // size)),
        "items": [
            {
                "name": item["market_hash_name"],
                "short": short_name(item["market_hash_name"]),
                "price": item.get("price"),
                "image": item.get("icon_url"),
                "category": item.get("category"),
                "weapon": item.get("weapon"),
                "rarity": rarity_slug(item.get("rarity"), item["market_hash_name"]),
                "offers": item.get("offers") or 0,
                "owners": item.get("owners") or 0,
            }
            for item in items
        ],
    }


async def api_catalog_available(request: web.Request) -> web.Response:
    """Скины, которые сейчас можно получить: они выставлены в активных объявлениях."""
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    category = request.query.get("category") or None
    weapon = request.query.get("weapon") or None
    query = request.query.get("q") or None
    try:
        page = max(0, int(request.query.get("page", "0")))
    except ValueError:
        page = 0
    try:
        size = min(50, max(1, int(request.query.get("size", "20"))))
    except ValueError:
        size = 20

    key = f"catalog:available:{category}:{weapon}:{query}:{page}:{size}"
    return await _cached_json(
        request, key, lambda: _available_items_payload(request, category, weapon, query, page, size)
    )


async def api_catalog_items(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    category = request.query.get("category") or None
    weapon = request.query.get("weapon") or None
    query = request.query.get("q") or None

    try:
        page = max(0, int(request.query.get("page", "0")))
    except ValueError:
        page = 0
    try:
        size = min(50, max(1, int(request.query.get("size", "20"))))
    except ValueError:
        size = 20

    filters = _catalog_filters(request)
    key = f"catalog:items:{category}:{weapon}:{query}:{page}:{size}:{sorted(filters.items())}"
    return await _cached_json(
        request,
        key,
        lambda: _catalog_items_payload(request, category, weapon, query, page, size, filters),
    )


async def api_offers_board(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    try:
        page = max(0, int(request.query.get("page", "0")))
    except ValueError:
        page = 0

    repos = _repos(request)
    query = (request.query.get("q") or "").strip() or None
    mine_only = (request.query.get("match") or "") in ("1", "true", "on")

    if mine_only:
        names = await repos.items.owner_names(user["id"])
        offers = await repos.offers.active_for_names(
            names, exclude_user_id=user["id"], limit=BOARD_PAGE_SIZE
        )
        total = len(offers)
    else:
        total = await repos.offers.count_active(query=query)
        offers = await repos.offers.get_active(
            limit=BOARD_PAGE_SIZE, offset=page * BOARD_PAGE_SIZE, query=query
        )

    # подсказка «мой скин подходит»: показываем на карточках, где хотят то, что у меня есть
    my_names = set(await repos.items.owner_names(user["id"]))
    cards = []
    for offer in offers:
        wanted = offer.get("wanted_name")
        match_name = wanted if wanted and wanted in my_names else None
        cards.append(_offer_json(offer, await _offer_items(repos, offer), user["id"], match_name))

    return web.json_response(
        {
            "total": total,
            "page": page,
            "pages": max(1, -(-total // BOARD_PAGE_SIZE)),
            "items": cards,
        }
    )


async def api_offers_create(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    body = await _body(request)
    item_ids = [int(item_id) for item_id in body.get("item_ids") or []][:10]
    wanted_text = str(body.get("wanted") or "").strip()

    if not item_ids:
        return web.json_response({"error": "Выберите хотя бы один скин"}, status=400)

    repos = _repos(request)
    owned = await repos.items.get_by_ids(item_ids)
    tradable_ids = {item["id"] for item in owned if item.get("is_tradable") and item["owner_id"] == user["id"]}
    if len(tradable_ids) != len(item_ids):
        return web.json_response({"error": "Часть предметов недоступна для обмена"}, status=400)

    wanted_name = None
    if wanted_text and wanted_text != "-":
        candidates = await find_candidates(repos, wanted_text)
        if candidates:
            wanted_name = candidates[0]["market_hash_name"]
        elif len(wanted_text) >= 2:
            return web.json_response(
                {"error": "Не нашёл такой скин в каталоге", "hint": "Опишите иначе или оставьте поле пустым"},
                status=400,
            )

    items = [item for item in owned]
    title = short_name(items[0]["market_hash_name"]) if items else "Обмен"
    if wanted_name:
        title = f"{title} → {short_name(wanted_name)}"

    offer_id = await repos.offers.create(
        creator_id=user["id"],
        title=title[:100],
        items_offered=item_ids,
        items_wanted=wanted_name or (wanted_text or "Не указано"),
        description=None if wanted_text in ("", "-") else wanted_text,
        wanted_name=wanted_name,
    )
    return web.json_response({"ok": True, "id": offer_id, "wanted": wanted_name})


async def api_my_offers(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    repos = _repos(request)
    offers = await repos.offers.get_by_creator(user["id"])
    return web.json_response(
        {"items": [_offer_json(offer, await _offer_items(repos, offer), user["id"]) for offer in offers[:15]]}
    )


async def _offer_action(request: web.Request, action: str) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    try:
        offer_id = int(request.match_info["offer_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad offer id"}, status=400)

    repos = _repos(request)
    offer = await repos.offers.get_by_id(offer_id)
    if not offer:
        return web.json_response({"error": "Предложение не найдено"}, status=404)

    if action == "accept":
        if offer["status"] not in ("active", "in_trade"):
            return web.json_response({"error": "Предложение больше не активно"}, status=400)
        if offer["creator_id"] == user["id"]:
            return web.json_response({"error": "Нельзя принять своё предложение"}, status=400)
        if not user.get("steam_trade_url"):
            return web.json_response({"error": "Сначала укажите Trade URL в профиле"}, status=400)

        body = await _body(request)
        try:
            my_item_ids = [int(item_id) for item_id in body.get("item_ids") or []][:10]
        except (TypeError, ValueError):
            return web.json_response({"error": "Некорректный список предметов"}, status=400)

        if my_item_ids:
            mine = await repos.items.get_by_ids(my_item_ids)
            blocked = [
                item for item in mine
                if item["owner_id"] != user["id"] or not item.get("is_tradable")
            ]
            if blocked or len(mine) != len(my_item_ids):
                return web.json_response(
                    {"error": "Часть предметов недоступна для обмена — обновите инвентарь"},
                    status=400,
                )

        trade_id = await repos.trades.create(
            buyer_id=user["id"], seller_id=offer["creator_id"], offer_id=offer_id
        )
        for item_id in json.loads(offer["items_offered"] or "[]"):
            await repos.trade_items.add(
                trade_id=trade_id,
                item_id=item_id,
                from_user_id=offer["creator_id"],
                to_user_id=user["id"],
            )
        for item_id in my_item_ids:
            await repos.trade_items.add(
                trade_id=trade_id,
                item_id=item_id,
                from_user_id=user["id"],
                to_user_id=offer["creator_id"],
            )

        # инициатор подтверждает сделку в момент отправки предложения
        await repos.trades.set_confirmed(trade_id, "buyer")
        await repos.offers.update_status(offer_id, "in_trade")
        await _notify_trade(request, "new", trade_id)
        return web.json_response({"ok": True, "trade_id": trade_id, "status": "pending"})

    if offer["creator_id"] != user["id"]:
        return web.json_response({"error": "Это не ваше предложение"}, status=403)

    if action == "cancel":
        await repos.offers.update_status(offer_id, "cancelled")
        return web.json_response({"ok": True})

    if action == "delete":
        await repos.offers.delete(offer_id)
        return web.json_response({"ok": True})

    return web.json_response({"error": "unknown action"}, status=400)


# ---------- сделки ----------


def _trade_json(trade: dict, user_id: int) -> dict:
    is_buyer = trade["buyer_id"] == user_id
    role = "buyer" if is_buyer else "seller"

    counterpart = (trade.get("seller_username") if is_buyer else trade.get("buyer_username")) or "—"
    counterpart_url = (
        trade.get("seller_trade_url" if is_buyer else "buyer_trade_url")
        if trade["status"] == "in_escrow"
        else None
    )

    actions = []
    if trade["status"] == "pending" and not trade.get(f"{role}_confirmed_at"):
        actions.append({"name": "confirm", "label": "✅ Подтвердить"})
    if trade["status"] == "in_escrow" and not trade.get(f"{role}_completed_at"):
        actions.append({"name": "complete", "label": "📦 Получил"})
    if trade["status"] == "holding":
        actions.append({"name": "rollback", "label": "↩️ Трейд отменён в Steam"})
    if trade["status"] in DISPUTE_TRADE_STATUSES and not trade.get("dispute_open"):
        actions.append({"name": "dispute", "label": "⚠️ Открыть спор"})
    if trade["status"] in {"pending", "confirmed", "in_escrow"}:
        actions.append({"name": "cancel", "label": "✖️ Отменить"})
    if trade["status"] == "completed":
        actions.append({"name": "rate", "label": "⭐ Оценить"})

    return {
        "id": trade["id"],
        "role": role,
        "status": trade["status"],
        "status_label": TRADE_STATUS_LABELS.get(trade["status"], trade["status"]),
        "counterpart": counterpart,
        "counterpart_id": trade.get("seller_id") if is_buyer else trade.get("buyer_id"),
        "counterpart_url": counterpart_url,
        "confirmed": bool(trade.get(f"{role}_confirmed_at")),
        "received": bool(trade.get(f"{role}_completed_at")),
        "dispute_open": bool(trade.get("dispute_open")),
        "finalize_at": trade.get("finalize_at"),
        "finalize_label": (
            format_deadline(trade.get("finalize_at")) if trade.get("finalize_at") else None
        ),
        "protection_note": (
            PROTECTION_NOTE if trade["status"] in {"in_escrow", "holding"} else None
        ),
        "actions": actions,
    }



async def _notify_trade(
    request: web.Request, event: str, trade_id: int, actor_id: int | None = None
) -> None:
    """Отправить уведомление по сделке через бота, если он есть в приложении."""
    bot = request.app.get(BOT_KEY)
    if bot is None:
        return
    trade = await _repos(request).trades.get_by_id(trade_id)
    if not trade:
        return
    web_app_url = _config(request).web_app_url
    try:
        if event == "new":
            await notifications.new_trade(bot, _repos(request), trade, web_app_url)
        elif event == "confirmed":
            await notifications.both_confirmed(bot, _repos(request), trade, web_app_url)
        elif event == "cancelled":
            await notifications.cancelled(bot, _repos(request), trade, actor_id, web_app_url)
        elif event == "received":
            await notifications.side_received(bot, _repos(request), trade, actor_id, web_app_url)
        elif event == "finalized":
            await notifications.finalized(bot, _repos(request), trade, web_app_url)
    except Exception as error:  # noqa: BLE001 — уведомление не должно ломать API
        logger.warning("Уведомление по сделке %s (%s) не ушло: %s", trade_id, event, error)



async def api_user_profile(request: web.Request) -> web.Response:
    """Публичный профиль участника: рейтинг, сделки, отзывы, Steam-профиль."""
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    try:
        user_id = int(request.match_info["user_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad user id"}, status=400)

    repos = _repos(request)
    target = await repos.users.get_by_id(user_id)
    if not target:
        return web.json_response({"error": "Пользователь не найден"}, status=404)

    reviews = await repos.ratings.get_for_user(user_id)
    average = await repos.ratings.get_average_rating(user_id)
    return web.json_response(
        {
            "id": target["id"],
            "name": format_author(target),
            "rating": round(average, 1),
            "trades_count": target.get("trades_count") or 0,
            "steam_persona": target.get("steam_persona"),
            "steam_profile_url": target.get("steam_profile_url"),
            "member_since": (target.get("created_at") or "")[:10],
            "reviews": [
                {
                    "score": review["score"],
                    "comment": review.get("comment"),
                    "from": review.get("from_username") or "участник",
                    "at": (review.get("created_at") or "")[:10],
                }
                for review in reviews[:10]
            ],
            "reviews_total": len(reviews),
        }
    )


async def api_trades(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    repos = _repos(request)
    trades = await repos.trades.get_by_user(user["id"], limit=20)

    items = []
    for trade in trades:
        was_holding = trade["status"] == "holding"
        trade = await finalize_due(repos, trade)
        if was_holding and trade["status"] == "completed":
            # срок Trade Protection истёк именно сейчас — можно ставить оценку
            await _notify_trade(request, "finalized", trade["id"])
        details = await trade_payload(repos, trade, user["id"])
        payload = _trade_json({**trade, **details}, user["id"])
        payload.update(details)
        items.append(payload)

    return web.json_response({"items": items})


async def api_trade_action(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    action = request.match_info.get("action", "")
    try:
        trade_id = int(request.match_info["trade_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad trade id"}, status=400)

    repos = _repos(request)
    trade = await repos.trades.get_by_id(trade_id)
    if not trade:
        return web.json_response({"error": "Сделка не найдена"}, status=404)
    trade = await finalize_due(repos, trade)

    if user["id"] not in {trade["buyer_id"], trade["seller_id"]}:
        return web.json_response({"error": "Это не ваша сделка"}, status=403)

    role = "buyer" if trade["buyer_id"] == user["id"] else "seller"

    if action == "confirm":
        if trade["status"] != "pending":
            return web.json_response({"error": "Сделка уже подтверждена"}, status=400)
        await repos.trades.set_confirmed(trade_id, role)
        trade = await repos.trades.get_by_id(trade_id)
        if trade["buyer_confirmed_at"] and trade["seller_confirmed_at"]:
            await repos.trades.update_status(trade_id, "in_escrow")
            await _notify_trade(request, "confirmed", trade_id)
            return web.json_response({"ok": True, "status": "in_escrow"})
        return web.json_response({"ok": True, "status": trade["status"]})

    if action == "complete":
        if trade["status"] != "in_escrow":
            return web.json_response({"error": "Сделка ещё не готова"}, status=400)
        if trade.get(f"{role}_completed_at"):
            return web.json_response({"error": "Вы уже отметили получение"}, status=400)

        await repos.trades.set_completed_side(trade_id, role)
        trade = await repos.trades.get_by_id(trade_id)
        if not (trade.get("buyer_completed_at") and trade.get("seller_completed_at")):
            await _notify_trade(request, "received", trade_id, user["id"])
        trade = await settle_after_receipt(repos, trade)
        if trade["status"] == "holding":
            return web.json_response(
                {
                    "ok": True,
                    "status": "holding",
                    "finalize_at": trade.get("finalize_at"),
                    "finalize_label": format_deadline(trade.get("finalize_at")),
                }
            )
        return web.json_response({"ok": True, "status": trade["status"]})

    if action == "rollback":
        if trade["status"] != "holding":
            return web.json_response(
                {"error": "Сделка не ждёт окончания Trade Protection"}, status=400
            )
        await repos.trades.update_status(trade_id, "cancelled")
        if trade.get("offer_id"):
            await repos.offers.update_status(trade["offer_id"], "active")
        await _notify_trade(request, "cancelled", trade_id, user["id"])
        return web.json_response({"ok": True, "status": "cancelled"})

    if action == "cancel":
        if trade["status"] not in {"pending", "confirmed", "in_escrow"}:
            return web.json_response({"error": "Сделку уже нельзя отменить"}, status=400)
        await repos.trades.update_status(trade_id, "cancelled")
        await _notify_trade(request, "cancelled", trade_id, user["id"])
        if trade.get("offer_id"):
            await repos.offers.update_status(trade["offer_id"], "active")
        return web.json_response({"ok": True, "status": "cancelled"})

    if action == "rate":
        body = await _body(request)
        try:
            score = int(body.get("score"))
        except (TypeError, ValueError):
            return web.json_response({"error": "Нужна оценка 1–5"}, status=400)
        if not 1 <= score <= 5:
            return web.json_response({"error": "Оценка от 1 до 5"}, status=400)
        if trade["status"] == "holding":
            deadline = format_deadline(trade.get("finalize_at"))
            return web.json_response(
                {"error": f"Оценка откроется после окончания Trade Protection ({deadline})"},
                status=400,
            )
        if trade["status"] != "completed":
            return web.json_response({"error": "Оценить можно только завершённую сделку"}, status=400)
        if await repos.ratings.exists(trade_id, user["id"]):
            return web.json_response({"error": "Вы уже оценили эту сделку"}, status=400)

        target_id = trade["seller_id"] if role == "buyer" else trade["buyer_id"]
        await repos.ratings.create(
            trade_id=trade_id, from_user_id=user["id"], to_user_id=target_id, score=score
        )
        rating = await repos.users.recompute_rating(target_id)
        return web.json_response({"ok": True, "counterparty_rating": rating})

    return web.json_response({"error": "unknown action"}, status=400)


async def api_trade_dispute(request: web.Request) -> web.Response:
    """Открыть спор по сделке: участник, причина текстом, один открытый спор на сделку."""
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    try:
        trade_id = int(request.match_info["trade_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad trade id"}, status=400)

    body = await _body(request)
    reason = str(body.get("reason") or "")
    repos = _repos(request)

    try:
        dispute_id, trade = await open_dispute(repos, trade_id, user["id"], reason)
    except DisputeError as error:
        return web.json_response({"error": str(error)}, status=error.status)

    bot: Bot | None = request.app.get(BOT_KEY)
    if bot is not None:
        await notify_dispute(bot, repos, trade, dispute_id, user["id"], reason, _config(request).admin_ids)
    else:
        logger.warning("Спор #%s открыт без уведомлений: бот не подключён к веб-приложению", dispute_id)

    return web.json_response({"ok": True, "dispute_id": dispute_id, "trade_id": trade_id})


# ---------- рейтинг ----------


async def api_rating(request: web.Request) -> web.Response:
    user = await _api_user(request)
    if user is None:
        return _unauthorized()

    repos = _repos(request)
    ratings = await repos.ratings.get_for_user(user["id"])
    average = await repos.ratings.get_average_rating(user["id"])

    return web.json_response(
        {
            "average": round(average, 2),
            "count": len(ratings),
            "items": [
                {
                    "score": rating["score"],
                    "author": f"@{rating['from_username']}" if rating.get("from_username") else "—",
                    "comment": rating.get("comment"),
                    "created_at": rating.get("created_at"),
                }
                for rating in ratings[:20]
            ],
        }
    )


# ---------- админка ----------


async def api_admin_stats(request: web.Request) -> web.Response:
    user, error = await _admin(request)
    if error:
        return error

    db = _repos(request).db
    stats = {}
    for key, query in {
        "users": "SELECT COUNT(*) AS cnt FROM users",
        "items": "SELECT COUNT(*) AS cnt FROM items",
        "offers": "SELECT COUNT(*) AS cnt FROM offers WHERE status = 'active'",
        "trades": "SELECT COUNT(*) AS cnt FROM trades",
        "disputes": "SELECT COUNT(*) AS cnt FROM disputes WHERE status = 'open'",
    }.items():
        cur = await db.execute(query)
        row = await cur.fetchone()
        stats[key] = row["cnt"] if row else 0

    return web.json_response(stats)


async def api_admin_users(request: web.Request) -> web.Response:
    user, error = await _admin(request)
    if error:
        return error

    cur = await _repos(request).db.execute(
        """
        SELECT telegram_id, username, first_name, is_steam_linked, is_banned, rating, trades_count
        FROM users ORDER BY id DESC LIMIT 50
        """
    )
    rows = await cur.fetchall()
    return web.json_response(
        {
            "items": [
                {
                    "telegram_id": row["telegram_id"],
                    "username": row["username"],
                    "first_name": row["first_name"],
                    "steam": bool(row["is_steam_linked"]),
                    "banned": bool(row["is_banned"]),
                    "rating": row["rating"],
                    "trades": row["trades_count"],
                }
                for row in rows
            ]
        }
    )


async def api_admin_ban(request: web.Request) -> web.Response:
    user, error = await _admin(request)
    if error:
        return error

    body = await _body(request)
    try:
        telegram_id = int(body.get("telegram_id"))
    except (TypeError, ValueError):
        return web.json_response({"error": "Нужен telegram_id"}, status=400)

    repos = _repos(request)
    target = await repos.users.get_by_telegram_id(telegram_id)
    if not target:
        return web.json_response({"error": "Пользователь не найден"}, status=404)

    if body.get("unban"):
        await repos.users.unban(target["id"])
    else:
        await repos.users.ban(target["id"])
    return web.json_response({"ok": True})


async def api_admin_disputes(request: web.Request) -> web.Response:
    user, error = await _admin(request)
    if error:
        return error

    disputes = await _repos(request).disputes.get_open()
    return web.json_response(
        {
            "items": [
                {
                    "id": dispute["id"],
                    "trade_id": dispute["trade_id"],
                    "author": f"@{dispute['opened_by_username']}" if dispute.get("opened_by_username") else "—",
                    "reason": dispute["reason"],
                }
                for dispute in disputes
            ]
        }
    )


async def api_admin_resolve(request: web.Request) -> web.Response:
    user, error = await _admin(request)
    if error:
        return error

    try:
        dispute_id = int(request.match_info["dispute_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad dispute id"}, status=400)

    body = await _body(request)
    note = str(body.get("note") or "решение администратора")
    await _repos(request).disputes.resolve(dispute_id, note)
    return web.json_response({"ok": True})


async def api_offer_accept(request: web.Request) -> web.Response:
    return await _offer_action(request, "accept")


async def api_offer_cancel(request: web.Request) -> web.Response:
    return await _offer_action(request, "cancel")


async def api_offer_delete(request: web.Request) -> web.Response:
    return await _offer_action(request, "delete")


def register_api_routes(app: web.Application) -> None:
    app.router.add_get("/api/me", api_me)
    app.router.add_post("/api/profile/steam", api_profile_steam)
    app.router.add_post("/api/profile/refresh", api_profile_refresh)
    app.router.add_get("/api/inventory", api_inventory)
    app.router.add_post("/api/inventory/sync", api_inventory_sync)
    app.router.add_get("/api/catalog", api_catalog)
    app.router.add_get("/api/catalog/tree", api_catalog_tree)
    app.router.add_get("/api/catalog/items", api_catalog_items)
    app.router.add_get("/api/catalog/available", api_catalog_available)
    app.router.add_get("/api/catalog/available/tree", api_catalog_available_tree)
    app.router.add_get("/api/offers", api_offers_board)
    app.router.add_post("/api/offers", api_offers_create)
    app.router.add_get("/api/my_offers", api_my_offers)
    app.router.add_post("/api/offers/{offer_id}/accept", api_offer_accept)
    app.router.add_post("/api/offers/{offer_id}/cancel", api_offer_cancel)
    app.router.add_post("/api/offers/{offer_id}/delete", api_offer_delete)
    app.router.add_get("/api/trades", api_trades)
    app.router.add_get("/api/users/{user_id}", api_user_profile)
    # конкретный путь спора регистрируется раньше общего {action}
    app.router.add_post("/api/trades/{trade_id}/dispute", api_trade_dispute)
    app.router.add_post("/api/trades/{trade_id}/{action}", api_trade_action)
    app.router.add_get("/api/rating", api_rating)
    app.router.add_get("/api/admin/stats", api_admin_stats)
    app.router.add_get("/api/admin/users", api_admin_users)
    app.router.add_post("/api/admin/ban", api_admin_ban)
    app.router.add_get("/api/admin/disputes", api_admin_disputes)
    app.router.add_post("/api/admin/disputes/{dispute_id}/resolve", api_admin_resolve)
