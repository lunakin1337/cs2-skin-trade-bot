"""Кэш ответов каталога: TTL в памяти процесса, ETag и версия каталога.

Каталог скинов меняется редко, а запросы Mini App к `/api/catalog*` идут на
каждое переключение таба, поэтому готовые ответы лежат в памяти веб-процесса до
`WEB_CACHE_TTL` секунд (по умолчанию 60).

Инвалидация работает и между процессами: импорт каталога и синхронизация
инвентаря поднимают версию каталога в таблице `settings`, а кэш хранит версию,
под которой построен ответ. Поэтому бот или CLI-импорт, переписавшие каталог,
сбрасывают кэш веб-процесса, не дожидаясь истечения TTL.
"""

import hashlib
import time
from typing import Optional

from database.repository import Repositories

CATALOG_VERSION_KEY = "catalog_version"


def make_etag(body: bytes) -> str:
    """Сильный ETag по телу ответа."""
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def etag_matches(if_none_match: Optional[str], etag: str) -> bool:
    """Совпадает ли заголовок If-None-Match с нашим ETag (список, `*`, `W/`)."""
    if not if_none_match:
        return False
    for candidate in if_none_match.split(","):
        candidate = candidate.strip()
        if candidate == "*":
            return True
        if candidate.startswith("W/"):
            candidate = candidate[2:]
        if candidate == etag:
            return True
    return False


class CatalogCache:
    """TTL-кэш готовых тел ответов, привязанный к версии каталога."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[float, str, str, bytes]] = {}

    def get(self, key: str, version: str, ttl: float) -> Optional[tuple[str, bytes]]:
        """Вернуть (etag, body) или None, если записи нет, она протухла или стара."""
        entry = self._entries.get(key)
        if entry is None:
            return None

        stored_at, entry_version, etag, body = entry
        if ttl <= 0 or entry_version != version or time.monotonic() - stored_at > ttl:
            self._entries.pop(key, None)
            return None
        return etag, body

    def put(self, key: str, version: str, body: bytes) -> str:
        """Положить тело в кэш и вернуть его ETag."""
        etag = make_etag(body)
        self._entries[key] = (time.monotonic(), version, etag, body)
        return etag

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


async def catalog_version(repos: Repositories) -> str:
    """Текущая версия каталога (в базе её нет — значит, «0»)."""
    return await repos.settings.get(CATALOG_VERSION_KEY) or "0"


async def bump_catalog_version(repos: Repositories) -> None:
    """Отметить каталог изменённым: кэши всех процессов станут неактуальными."""
    await repos.settings.set(CATALOG_VERSION_KEY, f"{time.time():.6f}")
