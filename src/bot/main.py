"""Точка входа бота."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import (
    admin_router,
    create_offer_router,
    escrow_router,
    inventory_router,
    offers_router,
    profile_router,
    ratings_router,
    start_router,
    trade_flow_router,
    trades_router,
)
from bot.middlewares.db import DbMiddleware
from bot.middlewares.logging import LoggingMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.utils.prices import close_price_fetcher
from bot.utils.steam import close_steam_client
from config.settings import BotConfig, load_config
from database import Repositories, init_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ROUTERS = (
    start_router,
    profile_router,
    inventory_router,
    offers_router,
    create_offer_router,
    trades_router,
    trade_flow_router,
    escrow_router,
    ratings_router,
    admin_router,
)


def create_dispatcher(config: BotConfig) -> Dispatcher:
    """Собрать диспетчер с роутерами (используется и в тестах)."""
    dispatcher = Dispatcher(storage=MemoryStorage())
    for router in ROUTERS:
        dispatcher.include_router(router)
    return dispatcher


async def main() -> None:
    config = load_config()
    db = await init_database(config.db_path)
    repos = Repositories(db)

    session = AiohttpSession(proxy=config.telegram_proxy) if config.telegram_proxy else None
    bot = Bot(
        token=config.token,
        session=session,
        default=DefaultBotProperties(parse_mode=config.parse_mode),
    )
    dispatcher = create_dispatcher(config)

    dispatcher.update.middleware(LoggingMiddleware())
    dispatcher.message.middleware(ThrottlingMiddleware(min_interval=0.5))
    dispatcher.callback_query.middleware(ThrottlingMiddleware(min_interval=0.2))
    dispatcher.message.middleware(DbMiddleware(repos, config))
    dispatcher.callback_query.middleware(DbMiddleware(repos, config))

    logger.info("Бот запущен")
    try:
        await dispatcher.start_polling(bot)
    finally:
        await close_price_fetcher()
        await close_steam_client()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
