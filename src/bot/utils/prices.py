"""Получение цен скинов CS2 из различных источников."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class SkinPrice:
    """Цена скина из одного источника."""
    source: str  # "steam_market", "csfloat", "buff163"
    market_hash_name: str
    price_usd: Optional[float] = None
    price_rub: Optional[float] = None
    volume_24h: Optional[int] = None
    updated_at: float = field(default_factory=time.time)
    raw_data: dict = field(default_factory=dict)


@dataclass
class AggregatedPrice:
    """Агрегированная цена из всех источников."""
    market_hash_name: str
    steam_market: Optional[SkinPrice] = None
    csfloat: Optional[SkinPrice] = None
    buff163: Optional[SkinPrice] = None
    
    @property
    def best_price_usd(self) -> Optional[float]:
        prices = [p.price_usd for p in [self.steam_market, self.csfloat, self.buff163] if p and p.price_usd]
        return min(prices) if prices else None
    
    @property
    def median_price_usd(self) -> Optional[float]:
        prices = sorted([p.price_usd for p in [self.steam_market, self.csfloat, self.buff163] if p and p.price_usd])
        if not prices:
            return None
        mid = len(prices) // 2
        return prices[mid] if len(prices) % 2 else (prices[mid-1] + prices[mid]) / 2


class PriceCache:
    """Простой in-memory кэш с TTL."""
    
    def __init__(self, ttl_seconds: int = 3600):
        self._cache: dict[str, tuple[float, AggregatedPrice]] = {}
        self.ttl = ttl_seconds
    
    def get(self, key: str) -> Optional[AggregatedPrice]:
        if key in self._cache:
            timestamp, value = self._cache[key]
            if time.time() - timestamp < self.ttl:
                return value
            else:
                del self._cache[key]
        return None
    
    def set(self, key: str, value: AggregatedPrice) -> None:
        self._cache[key] = (time.time(), value)
    
    def clear(self) -> None:
        self._cache.clear()


class PriceFetcher:
    """Получение цен из различных источников."""
    
    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        cache_ttl: int = 3600
    ):
        self._session = session
        self._own_session = session is None
        self.cache = PriceCache(ttl_seconds=cache_ttl)
        self._semaphore = asyncio.Semaphore(5)  # Лимит одновременных запросов
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
        return self._session
    
    async def close(self) -> None:
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()
    
    async def _fetch_steam_market(self, market_hash_name: str) -> Optional[SkinPrice]:
        """Получить цену с Steam Community Market."""
        # Steam Market API неофициальный, используем публичный эндпоинт
        # https://steamcommunity.com/market/priceoverview/?appid=730&currency=1&market_hash_name=...
        session = await self._get_session()
        url = "https://steamcommunity.com/market/priceoverview/"
        params = {
            "appid": "730",
            "currency": "1",  # USD
            "market_hash_name": market_hash_name,
        }
        
        try:
            async with self._semaphore:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    
            if not data.get("success"):
                return None
            
            # lowest_price формат: "$0.50 USD"
            lowest = data.get("lowest_price", "").replace("$", "").replace(" USD", "").replace(",", "")
            volume = data.get("volume", "").replace(",", "")
            
            return SkinPrice(
                source="steam_market",
                market_hash_name=market_hash_name,
                price_usd=float(lowest) if lowest else None,
                volume_24h=int(volume) if volume else None,
                raw_data=data
            )
        except Exception as e:
            logger.debug(f"Steam Market error for {market_hash_name}: {e}")
            return None
    
    async def _fetch_csfloat(self, market_hash_name: str) -> Optional[SkinPrice]:
        """Получить цену с CSFloat (требует API ключ для полноценной работы)."""
        # CSFloat API: https://csfloat.com/api/v1/listings?market_hash_name=...
        # Публичный доступ ограничен, используем упрощённый вариант
        session = await self._get_session()
        url = "https://csfloat.com/api/v1/listings"
        params = {
            "market_hash_name": market_hash_name,
            "limit": 1,
            "sort_by": "lowest_price",
        }
        
        try:
            async with self._semaphore:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
            
            listings = data.get("data", [])
            if not listings:
                return None
            
            # Цена в центах
            price_cents = listings[0].get("price", 0)
            
            return SkinPrice(
                source="csfloat",
                market_hash_name=market_hash_name,
                price_usd=price_cents / 100,
                raw_data=listings[0]
            )
        except Exception as e:
            logger.debug(f"CSFloat error for {market_hash_name}: {e}")
            return None
    
    async def _fetch_buff163(self, market_hash_name: str) -> Optional[SkinPrice]:
        """Получить цену с Buff163 (требует куки/сессию)."""
        # Buff163 требует авторизацию, публичный API ограничен
        # Можно использовать неофициальные эндпоинты, но они нестабильны
        return None
    
    async def fetch_price(self, market_hash_name: str, use_cache: bool = True) -> AggregatedPrice:
        """Получить агрегированную цену для скина."""
        if use_cache:
            cached = self.cache.get(market_hash_name)
            if cached:
                return cached
        
        # Параллельно запрашиваем все источники
        steam_task = self._fetch_steam_market(market_hash_name)
        csfloat_task = self._fetch_csfloat(market_hash_name)
        buff_task = self._fetch_buff163(market_hash_name)
        
        steam_price, csfloat_price, buff_price = await asyncio.gather(
            steam_task, csfloat_task, buff_task, return_exceptions=True
        )
        
        # Обрабатываем исключения
        if isinstance(steam_price, Exception):
            steam_price = None
        if isinstance(csfloat_price, Exception):
            csfloat_price = None
        if isinstance(buff_price, Exception):
            buff_price = None
        
        result = AggregatedPrice(
            market_hash_name=market_hash_name,
            steam_market=steam_price,
            csfloat=csfloat_price,
            buff163=buff_price,
        )
        
        if use_cache:
            self.cache.set(market_hash_name, result)
        
        return result
    
    async def fetch_multiple(self, market_hash_names: list[str]) -> dict[str, AggregatedPrice]:
        """Получить цены для нескольких скинов сразу."""
        tasks = [self.fetch_price(name) for name in market_hash_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        output = {}
        for name, result in zip(market_hash_names, results):
            if isinstance(result, Exception):
                output[name] = AggregatedPrice(market_hash_name=name)
            else:
                output[name] = result
        
        return output


# Глобальный экземпляр
_price_fetcher: Optional[PriceFetcher] = None


async def get_price_fetcher() -> PriceFetcher:
    global _price_fetcher
    if _price_fetcher is None:
        _price_fetcher = PriceFetcher()
    return _price_fetcher


async def close_price_fetcher() -> None:
    global _price_fetcher
    if _price_fetcher:
        await _price_fetcher.close()
        _price_fetcher = None