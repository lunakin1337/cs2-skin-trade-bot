"""Steam Web API wrapper для CS2 (app_id=730)."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

from config.settings import load_config

logger = logging.getLogger(__name__)

STEAM_API_BASE = "https://api.steampowered.com"
CS2_APP_ID = 730
CS2_CONTEXT_ID = 2


@dataclass
class SteamItem:
    """Предмет из Steam инвентаря."""
    asset_id: str
    class_id: str
    instance_id: str
    amount: int
    market_hash_name: Optional[str] = None
    market_name: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    quality: Optional[str] = None
    float_value: Optional[float] = None
    paint_seed: Optional[int] = None
    stickers: Optional[list] = None
    tradable: bool = True
    marketable: bool = True


@dataclass
class SteamInventory:
    """Инвентарь пользователя."""
    steam_id: str
    items: list[SteamItem]
    total_count: int
    success: bool
    error: Optional[str] = None


class SteamAPI:
    """Обёртка над Steam Web API."""

    def __init__(self, api_key: Optional[str] = None, session: Optional[aiohttp.ClientSession] = None):
        self.api_key = api_key or load_config().steam_api_key
        self._session = session
        self._own_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def close(self) -> None:
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, endpoint: str, params: dict) -> dict:
        """Выполнить GET запрос к Steam API."""
        session = await self._get_session()
        url = f"{STEAM_API_BASE}{endpoint}"
        
        if self.api_key:
            params["key"] = self.api_key

        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise SteamAPIError(f"HTTP {resp.status}: {text}")
            return await resp.json()

    async def get_player_inventory(
        self,
        steam_id: str,
        app_id: int = CS2_APP_ID,
        context_id: int = CS2_CONTEXT_ID,
        tradable_only: bool = True
    ) -> SteamInventory:
        """
        Получить инвентарь игрока.
        
        Требует: Steam API Key (для приватных инвентарей) или публичный инвентарь.
        """
        endpoint = f"/IEconItems_{app_id}/GetPlayerItems/v1/"
        params = {
            "steamid": steam_id,
        }
        
        try:
            data = await self._request(endpoint, params)
            result = data.get("result", {})
            
            if result.get("status") != 1:
                error = result.get("statusDetail", "Unknown error")
                return SteamInventory(
                    steam_id=steam_id,
                    items=[],
                    total_count=0,
                    success=False,
                    error=error
                )

            items = []
            for item_data in result.get("items", []):
                if tradable_only and not item_data.get("flags", 0) & 1:
                    continue
                    
                item = SteamItem(
                    asset_id=str(item_data.get("id", "")),
                    class_id=str(item_data.get("classid", "")),
                    instance_id=str(item_data.get("instanceid", "")),
                    amount=item_data.get("amount", 1),
                    tradable=bool(item_data.get("flags", 0) & 1),
                    marketable=bool(item_data.get("flags", 0) & 2),
                )
                items.append(item)

            return SteamInventory(
                steam_id=steam_id,
                items=items,
                total_count=len(items),
                success=True
            )

        except Exception as e:
            logger.error(f"Ошибка получения инвентаря {steam_id}: {e}")
            return SteamInventory(
                steam_id=steam_id,
                items=[],
                total_count=0,
                success=False,
                error=str(e)
            )

    async def get_schema(self, app_id: int = CS2_APP_ID, language: str = "ru") -> dict:
        """
        Получить схему предметов игры (названия, качество, тип и т.д.).
        Кэшировать результат — схема меняется редко.
        """
        endpoint = f"/IEconItems_{app_id}/GetSchema/v2/"
        params = {"language": language}
        data = await self._request(endpoint, params)
        return data.get("result", {})

    async def resolve_item_details(
        self,
        items: list[SteamItem],
        schema: Optional[dict] = None
    ) -> list[SteamItem]:
        """
        Обогатить предметы данными из схемы (market_hash_name, quality, type и т.д.).
        """
        if schema is None:
            schema = await self.get_schema()

        items_by_classid = {}
        for item in schema.get("items", []):
            classid = str(item.get("defindex", ""))
            items_by_classid[classid] = item

        for item in items:
            schema_item = items_by_classid.get(item.class_id)
            if schema_item:
                item.market_hash_name = schema_item.get("market_hash_name")
                item.market_name = schema_item.get("market_name")
                item.name = schema_item.get("name")
                item.type = schema_item.get("type")
                item.quality = str(schema_item.get("quality", ""))

        return items


class SteamAPIError(Exception):
    """Ошибка Steam API."""
    pass


# Глобальный экземпляр для переиспользования
_steam_api: Optional[SteamAPI] = None


async def get_steam_api() -> SteamAPI:
    """Получить глобальный экземпляр SteamAPI."""
    global _steam_api
    if _steam_api is None:
        _steam_api = SteamAPI()
    return _steam_api


async def close_steam_api() -> None:
    """Закрыть глобальный экземпляр."""
    global _steam_api
    if _steam_api:
        await _steam_api.close()
        _steam_api = None