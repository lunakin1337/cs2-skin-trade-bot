"""Клиент Steam: профиль, trade URL и публичный инвентарь CS2.

Инвентарь берётся из публичного эндпоинта Steam Community
(``/inventory/<steamid64>/730/2``) — он не требует API-ключа и отдаёт
сразу имена, теги и хеши картинок. Steam Web API нужен только для
публичного профиля (имя, аватар).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional
from urllib.parse import parse_qs, urlparse

import aiohttp

logger = logging.getLogger(__name__)

STEAM_API_BASE = "https://api.steampowered.com"
STEAM_COMMUNITY_BASE = "https://steamcommunity.com"
STEAM_IMAGE_BASE = "https://community.cloudflare.steamstatic.com/economy/image"
TRADE_URL_BASE = "https://steamcommunity.com/tradeoffer/new/"
CS2_APP_ID = 730
CS2_CONTEXT_ID = 2
INVENTORY_PAGE_SIZE = 1000
REQUEST_TIMEOUT = 20
RATE_LIMIT_RETRY_DELAY = 2.0

PARTNER_RE = re.compile(r"^\d{1,12}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{4,32}$")

STEAM_DESCRIPTION_LIMIT = 10

# Steam отдаёт флаг tradable=1 даже для скинов с торговым кулдауном,
# а срок блокировки лежит текстом в owner_descriptions.
TRADE_HOLD_MARKERS = (
    "tradable after",
    "обмен возможен после",
    "нельзя обменять до",
    "торговый кулдаун",
    "trade cooldown",
)


class SteamError(Exception):
    """Ошибка обращения к Steam с машиночитаемой причиной."""

    def __init__(self, message: str, kind: str = "unavailable"):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class TradeUrl:
    """Разобранный Steam Trade URL."""

    partner: str
    token: str

    @property
    def url(self) -> str:
        return f"{TRADE_URL_BASE}?partner={self.partner}&token={self.token}"

    @property
    def masked(self) -> str:
        return f"partner={self.partner}, token=•••{self.token[-2:]}"


def parse_trade_url(raw: str | None) -> Optional[TradeUrl]:
    """Разобрать и нормализовать Steam Trade URL. Возвращает None, если ссылка невалидна."""
    if not raw:
        return None

    candidate = raw.strip()
    if not candidate:
        return None

    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower().removeprefix("www.") != "steamcommunity.com":
        return None
    if parsed.path.rstrip("/") != "/tradeoffer/new":
        return None

    query = parse_qs(parsed.query)
    partner = (query.get("partner") or [""])[0].strip()
    token = (query.get("token") or [""])[0].strip()

    if not PARTNER_RE.match(partner) or not TOKEN_RE.match(token):
        return None

    return TradeUrl(partner=partner, token=token)


def build_image_url(icon_url: Optional[str], size: str = "360fx360f") -> Optional[str]:
    """Собрать полный URL картинки скина из хеша Steam."""
    if not icon_url:
        return None
    return f"{STEAM_IMAGE_BASE}/{icon_url.strip('/')}/{size}"


@dataclass(frozen=True)
class SteamProfile:
    """Публичный профиль Steam."""

    steam_id: str
    persona_name: str
    profile_url: str
    avatar_url: Optional[str] = None


@dataclass
class SteamItem:
    """Предмет инвентаря CS2."""

    asset_id: str
    class_id: str
    instance_id: str
    amount: int = 1
    market_hash_name: Optional[str] = None
    name: Optional[str] = None
    item_type: Optional[str] = None
    rarity: Optional[str] = None
    quality: Optional[str] = None
    exterior: Optional[str] = None
    icon_url: Optional[str] = None
    image_url: Optional[str] = None
    tradable: bool = True
    marketable: bool = True
    commodity: bool = False
    trade_hold: bool = False

    def as_row(self) -> dict[str, Any]:
        """Представить предмет строкой для ItemRepository.sync."""
        return {
            "steam_asset_id": self.asset_id,
            "market_hash_name": self.market_hash_name or self.name or "Unknown item",
            "item_name": self.name,
            "item_type": self.item_type,
            "rarity": self.rarity,
            "quality": self.quality,
            "exterior": self.exterior,
            "icon_url": self.icon_url,
            "image_url": self.image_url,
            "class_id": self.class_id,
            "instance_id": self.instance_id,
            "is_tradable": self.tradable and not self.trade_hold,
            "is_marketable": self.marketable,
        }


@dataclass
class SteamInventory:
    """Результат загрузки инвентаря."""

    steam_id: str
    items: list[SteamItem] = field(default_factory=list)
    success: bool = True
    error: Optional[str] = None
    error_kind: Optional[str] = None

    @property
    def total_count(self) -> int:
        return len(self.items)

    def rows(self) -> list[dict[str, Any]]:
        return [item.as_row() for item in self.items]


def has_trade_hold(description: dict[str, Any]) -> bool:
    """Есть ли у предмета торговый кулдаун (Steam пишет срок в owner_descriptions)."""
    for entry in description.get("owner_descriptions") or []:
        value = str(entry.get("value") or "").lower()
        if any(marker in value for marker in TRADE_HOLD_MARKERS):
            return True
    return False


def _description_key(description: dict[str, Any]) -> tuple[str, str]:
    return str(description.get("classid", "")), str(description.get("instanceid", ""))


def parse_inventory(assets: Iterable[dict[str, Any]], descriptions: Iterable[dict[str, Any]]) -> list[SteamItem]:
    """Собрать предметы из ответа Steam Community inventory."""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for description in descriptions:
        by_key[_description_key(description)] = description

    items: list[SteamItem] = []
    for asset in assets:
        class_id = str(asset.get("classid", ""))
        instance_id = str(asset.get("instanceid", ""))
        description = by_key.get((class_id, instance_id), {})

        tags = {
            str(tag.get("category", "")).lower(): tag.get("localized_tag_name")
            for tag in description.get("tags") or []
        }
        icon = description.get("icon_url")
        trade_hold = has_trade_hold(description)
        market_hash_name = description.get("market_hash_name")
        name = description.get("name") or market_hash_name

        try:
            amount = int(asset.get("amount", 1) or 1)
        except (TypeError, ValueError):
            amount = 1

        items.append(
            SteamItem(
                asset_id=str(asset.get("assetid", "")),
                class_id=class_id,
                instance_id=instance_id,
                amount=amount,
                market_hash_name=market_hash_name,
                name=name,
                item_type=tags.get("type") or description.get("type"),
                rarity=tags.get("rarity"),
                quality=tags.get("quality"),
                exterior=tags.get("exterior"),
                icon_url=icon,
                image_url=build_image_url(icon),
                tradable=bool(description.get("tradable", 0)) and not trade_hold,
                marketable=bool(description.get("marketable", 0)),
                commodity=bool(description.get("commodity", 0)),
                trade_hold=trade_hold,
            )
        )

    return items


class SteamClient:
    """Асинхронный клиент Steam Web API и Steam Community."""

    def __init__(self, api_key: str = "", session: Optional[aiohttp.ClientSession] = None):
        self.api_key = api_key
        self._session = session
        self._own_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                headers={"User-Agent": "CS2SkinTradeBot/0.2 (+telegram)"},
            )
        return self._session

    async def close(self) -> None:
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    async def _get_json(self, url: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        session = await self._get_session()
        for attempt in range(2):
            async with session.get(url, params=params) as response:
                if response.status == 429:
                    if attempt == 0:
                        await asyncio.sleep(RATE_LIMIT_RETRY_DELAY)
                        continue
                    raise SteamError("Steam ограничил частоту запросов", kind="rate_limited")
                if response.status in {401, 403}:
                    raise SteamError("Инвентарь закрыт или профиль недоступен", kind="forbidden")
                if response.status >= 500:
                    raise SteamError("Steam временно недоступен", kind="unavailable")
                if not response.ok:
                    raise SteamError(f"Steam ответил HTTP {response.status}", kind="unavailable")
                try:
                    return await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError):
                    raise SteamError("Steam вернул некорректный ответ", kind="unavailable")
        return None

    async def fetch_profile(self, steam_id: str) -> Optional[SteamProfile]:
        """Публичное имя и аватар. Требует STEAM_API_KEY."""
        if not self.api_key:
            raise SteamError("STEAM_API_KEY не задан", kind="no_api_key")

        data = await self._get_json(
            f"{STEAM_API_BASE}/ISteamUser/GetPlayerSummaries/v2/",
            {"key": self.api_key, "steamids": steam_id, "format": "json"},
        )
        players = ((data or {}).get("response") or {}).get("players") or []
        if not players:
            return None

        player = players[0]
        return SteamProfile(
            steam_id=str(player.get("steamid", steam_id)),
            persona_name=player.get("personaname") or "",
            profile_url=player.get("profileurl") or f"https://steamcommunity.com/profiles/{steam_id}",
            avatar_url=player.get("avatarfull") or player.get("avatarmedium"),
        )

    async def fetch_inventory(self, steam_id: str, language: str = "russian") -> SteamInventory:
        """Загрузить весь инвентарь CS2, обходя постраничную выдачу Steam."""
        url = f"{STEAM_COMMUNITY_BASE}/inventory/{steam_id}/{CS2_APP_ID}/{CS2_CONTEXT_ID}"
        assets: list[dict[str, Any]] = []
        descriptions: dict[tuple[str, str], dict[str, Any]] = {}
        start_assetid: Optional[str] = None

        try:
            for _ in range(STEAM_DESCRIPTION_LIMIT):
                params: dict[str, Any] = {"l": language, "count": INVENTORY_PAGE_SIZE}
                if start_assetid:
                    params["start_assetid"] = start_assetid

                data = await self._get_json(url, params)
                if not data or not data.get("success"):
                    return SteamInventory(
                        steam_id=steam_id,
                        success=False,
                        error="Инвентарь закрыт или не существует",
                        error_kind="forbidden",
                    )

                assets.extend(data.get("assets") or [])
                for description in data.get("descriptions") or []:
                    descriptions[_description_key(description)] = description

                if not data.get("more_items"):
                    break
                start_assetid = data.get("last_assetid")
                if not start_assetid:
                    break
        except SteamError as error:
            return SteamInventory(
                steam_id=steam_id,
                success=False,
                error=str(error),
                error_kind=error.kind,
            )

        items = parse_inventory(assets, descriptions.values())
        return SteamInventory(steam_id=steam_id, items=items, success=True)


_steam_client: Optional[SteamClient] = None


def get_steam_client(api_key: str = "") -> SteamClient:
    """Переиспользуемый клиент на процесс."""
    global _steam_client
    if _steam_client is None:
        _steam_client = SteamClient(api_key=api_key)
    elif api_key and not _steam_client.api_key:
        _steam_client.api_key = api_key
    return _steam_client


async def close_steam_client() -> None:
    global _steam_client
    if _steam_client is not None:
        await _steam_client.close()
        _steam_client = None
