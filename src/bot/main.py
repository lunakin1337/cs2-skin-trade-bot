"""Точка входа бота."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config.settings import load_config
from database import Database
from database.models import SCHEMA
from database.repository import Repositories
from bot.middlewares.db import DbMiddleware
from bot.handlers import (
    start_router,
    profile_router,
    inventory_router,
    offers_router,
    trades_router,
    admin_router,
    create_offer_router,
    trade_flow_router,
    escrow_router,
    ratings_router,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()

    bot = Bot(token=config.token)
    dp = Dispatcher(storage=MemoryStorage())

    db = Database(db_path=config.db_path)
    await db.connect()
    await db.init_schema(SCHEMA)

    repos = Repositories(db)

    # Middleware для передачи repos и config в хендлеры
    dp.message.middleware(DbMiddleware(repos, config))
    dp.callback_query.middleware(DbMiddleware(repos, config))

    # Регистрация роутеров
    dp.include_router(start_router)
    dp.include_router(profile_router)
    dp.include_router(inventory_router)
    dp.include_router(offers_router)
    dp.include_router(trades_router)
    dp.include_router(admin_router)
    dp.include_router(create_offer_router)
    dp.include_router(trade_flow_router)
    dp.include_router(escrow_router)
    dp.include_router(ratings_router)

    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())