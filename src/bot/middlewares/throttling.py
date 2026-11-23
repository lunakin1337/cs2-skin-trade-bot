"""Middleware троттлинга: лишние апдейты отбрасываются, а не ждут в очереди."""

import logging
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

logger = logging.getLogger(__name__)

CLEANUP_THRESHOLD = 5000
CLEANUP_WINDOW_SECONDS = 60.0


class ThrottlingMiddleware(BaseMiddleware):
    """Не даёт одному пользователю заваливать бота апдейтами."""

    def __init__(self, min_interval: float = 0.5):
        self.min_interval = min_interval
        self._last_seen: Dict[int, float] = {}

    def _prune(self, now: float) -> None:
        if len(self._last_seen) < CLEANUP_THRESHOLD:
            return
        self._last_seen = {
            user_id: seen
            for user_id, seen in self._last_seen.items()
            if now - seen < CLEANUP_WINDOW_SECONDS
        }

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        from_user = getattr(event, "from_user", None)
        user_id = getattr(from_user, "id", None)

        if user_id is not None:
            now = time.monotonic()
            last_seen = self._last_seen.get(user_id)
            if last_seen is not None and now - last_seen < self.min_interval:
                logger.debug("Троттлинг: пропускаю апдейт от %s", user_id)
                return None
            self._last_seen[user_id] = now
            self._prune(now)

        return await handler(event, data)
