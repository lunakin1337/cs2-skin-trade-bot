"""Middleware для передачи репозиториев и конфига в хендлеры."""

from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from database.repository import Repositories
from config.settings import BotConfig


class DbMiddleware(BaseMiddleware):
    def __init__(self, repos: Repositories, config: BotConfig):
        self.repos = repos
        self.config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data["repos"] = self.repos
        data["config"] = self.config
        return await handler(event, data)