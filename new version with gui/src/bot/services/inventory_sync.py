"""Синхронизация инвентаря со Steam (общая логика для бота и Mini App)."""

import logging
from typing import Optional

from bot.utils.prices import get_price_fetcher
from bot.utils.skin_categories import classify, rarity_slug
from bot.utils.steam import SteamClient, SteamInventory, get_steam_client
from catalog_cache import bump_catalog_version
from config.settings import BotConfig
from database.repository import Repositories

logger = logging.getLogger(__name__)

PRICE_SYNC_LIMIT = 20

ERROR_HINTS = {
    "forbidden": (
        "Инвентарь CS2 закрыт или не существует. "
        "Steam → Инвентарь → «Настройки приватности» → «Открытый»."
    ),
    "rate_limited": "Steam ограничил частоту запросов. Попробуйте через минуту.",
    "unavailable": "Steam временно недоступен. Попробуйте позже.",
}


async def refresh_prices(
    repos: Repositories,
    user_id: int,
    inventory: SteamInventory,
) -> int:
    """Обновить цены для части предметов и вернуть их количество."""
    names = [item.market_hash_name for item in inventory.items if item.market_hash_name]
    prices = await get_price_fetcher().fetch_prices(names, limit=PRICE_SYNC_LIMIT)
    if prices:
        await repos.items.apply_prices(user_id, prices)
    return len(prices)


async def sync_inventory(
    repos: Repositories,
    user: dict,
    config: BotConfig,
    client: Optional[SteamClient] = None,
) -> dict:
    """Загрузить инвентарь пользователя из Steam и сохранить в базу.

    Возвращает отчёт: ``ok``, ``error``/``hint``, счётчики и всего предметов.
    """
    steam_id = user.get("steam_id")
    if not steam_id:
        return {"ok": False, "error": "SteamID не привязан — заполните профиль."}

    steam = client or get_steam_client(config.steam_api_key)
    inventory = await steam.fetch_inventory(steam_id)

    if not inventory.success:
        return {
            "ok": False,
            "error": inventory.error or "Steam не отдал инвентарь",
            "hint": ERROR_HINTS.get(inventory.error_kind or "", "Попробуйте позже."),
            "error_kind": inventory.error_kind,
        }

    if not inventory.items:
        return {
            "ok": False,
            "error": "В инвентаре CS2 нет предметов или он пуст после фильтра Steam.",
        }

    created, updated, removed = await repos.items.sync(user["id"], inventory.rows())
    priced = await refresh_prices(repos, user["id"], inventory)

    # предметы, ушедшие из инвентаря, не должны висеть в активных объявлениях
    cancelled = await repos.offers.cancel_with_missing_items(user["id"])
    if cancelled:
        await bump_catalog_version(repos)

    # что видели в инвентаре — попадает в каталог для «хочу»
    await repos.skins.upsert_many(
        [
            {
                "market_hash_name": item.market_hash_name,
                "name": item.name,
                "icon_url": item.icon_url,
                "category": classify(item.market_hash_name)[0],
                "weapon": classify(item.market_hash_name)[1],
                "rarity": rarity_slug(getattr(item, "rarity", None), item.market_hash_name),
            }
            for item in inventory.items
            if item.market_hash_name
        ]
    )
    await repos.users.touch_inventory_sync(user["id"])
    # инвентарь подмешивает скины в каталог — сбрасываем кэш ответов Mini App
    await bump_catalog_version(repos)

    return {
        "ok": True,
        "found": inventory.total_count,
        "created": created,
        "updated": updated,
        "removed": removed,
        "priced": priced,
        "offers_cancelled": cancelled,
    }
