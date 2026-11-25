"""Цены скинов CS2: Steam Community Market и CSFloat."""

import asyncio
import logging
import time
from typing import Iterable, Optional

import aiohttp

logger = logging.getLogger(__name__)

STEAM_MARKET_URL = "https://steamcommunity.com/market/priceoverview/"
CSFLOAT_URL = "https://csfloat.com/api/v1/listings"
PRICE_CURRENCY_USD = "1"
MAX_CONCURRENT_REQUESTS = 5
DEFAULT_CACHE_TTL = 3600


class PriceCache:
    """Кэш цен с TTL."""

    def __init__(self, ttl_seconds: int = DEFAULT_CACHE_TTL):
        self.ttl = ttl_seconds
        self._values: dict[str, tuple[float, Optional[float]]] = {}

    def get(self, key: str) -> tuple[bool, Optional[float]]:
        cached = self._values.get(key)
        if cached is None:
            return False, None
        timestamp, price = cached
        if time.time() - timestamp > self.ttl:
            del self._values[key]
            return False, None
        return True, price

    def set(self, key: str, price: Optional[float]) -> None:
        self._values[key] = (time.time(), price)

    def clear(self) -> None:
        self._values.clear()


class PriceFetcher:
    """Получение минимальной цены скина из публичных источников."""

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, cache_ttl: int = DEFAULT_CACHE_TTL):
        self._session = session
        self._own_session = session is None
        self.cache = PriceCache(ttl_seconds=cache_ttl)
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                headers={"User-Agent": "Mozilla/5.0 (compatible; CS2SkinTradeBot/0.2)"},
            )
        return self._session

    async def close(self) -> None:
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    async def _request_json(self, url: str, params: dict[str, str]) -> Optional[dict]:
        session = await self._get_session()
        async with self._semaphore:
            async with session.get(url, params=params) as response:
                if not response.ok:
                    return None
                try:
                    return await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError):
                    return None

    async def _steam_price(self, market_hash_name: str) -> Optional[float]:
        data = await self._request_json(
            STEAM_MARKET_URL,
            {
                "appid": "730",
                "currency": PRICE_CURRENCY_USD,
                "market_hash_name": market_hash_name,
            },
        )
        if not data or not data.get("success"):
            return None

        raw = (data.get("lowest_price") or data.get("median_price") or "").strip()
        cleaned = raw.replace("$", "").replace("USD", "").replace(",", "").strip()
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    async def _csfloat_price(self, market_hash_name: str) -> Optional[float]:
        data = await self._request_json(
            CSFLOAT_URL,
            {"market_hash_name": market_hash_name, "limit": "1", "sort_by": "lowest_price"},
        )
        listings = (data or {}).get("data") or []
        if not listings:
            return None

        price_cents = listings[0].get("price")
        if not isinstance(price_cents, (int, float)) or price_cents <= 0:
            return None
        return round(price_cents / 100, 2)

    async def fetch_price(self, market_hash_name: str, use_cache: bool = True) -> Optional[float]:
        """Минимальная цена в USD или None, если источники не ответили."""
        if not market_hash_name:
            return None
        if use_cache:
            cached, price = self.cache.get(market_hash_name)
            if cached:
                return price

        steam_price, csfloat_price = await asyncio.gather(
            self._steam_price(market_hash_name),
            self._csfloat_price(market_hash_name),
            return_exceptions=True,
        )
        candidates = [
            price
            for price in (steam_price, csfloat_price)
            if isinstance(price, (int, float)) and price > 0
        ]
        best = min(candidates) if candidates else None

        if use_cache:
            self.cache.set(market_hash_name, best)
        return best

    async def fetch_prices(
        self,
        market_hash_names: Iterable[str],
        limit: int = 20,
    ) -> dict[str, float]:
        """Цены для первых ``limit`` уникальных имён."""
        unique_names = list(dict.fromkeys(name for name in market_hash_names if name))[:limit]
        if not unique_names:
            return {}

        results = await asyncio.gather(
            *(self.fetch_price(name) for name in unique_names),
            return_exceptions=True,
        )
        return {
            name: price
            for name, price in zip(unique_names, results)
            if isinstance(price, (int, float)) and price > 0
        }


_price_fetcher: Optional[PriceFetcher] = None


def get_price_fetcher() -> PriceFetcher:
    global _price_fetcher
    if _price_fetcher is None:
        _price_fetcher = PriceFetcher()
    return _price_fetcher


async def close_price_fetcher() -> None:
    global _price_fetcher
    if _price_fetcher is not None:
        await _price_fetcher.close()
        _price_fetcher = None
