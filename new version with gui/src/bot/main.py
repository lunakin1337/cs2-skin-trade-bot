"""Точка входа бота."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from bot.utils.sqlite_storage import SQLiteStorage

from bot.handlers import (
    admin_router,
    create_offer_router,
    escrow_router,
    inventory_router,
    offers_router,
    profile_router,
    ratings_router,
    skins_router,
    start_router,
    trade_flow_router,
    trades_router,
)
from bot.middlewares.db import DbMiddleware
from bot.middlewares.logging import LoggingMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.services.skin_query_llm import log_llm_status
from bot.utils.prices import close_price_fetcher
from bot.utils.steam import close_steam_client
from config.settings import BotConfig, load_config, load_llm_config
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
    skins_router,
    admin_router,
)


async def wait_for_telegram(bot: Bot, attempts: int = 30, delay: float = 15.0):
    """Дождаться Bot API: на общих IP Telegram отвечает flood control."""
    for attempt in range(1, attempts + 1):
        try:
            return await bot.me()
        except TelegramRetryAfter as error:
            pause = max(float(error.retry_after), 5.0)
            logger.warning(
                "Telegram flood control, повтор через %.0f с (%s/%s)", pause, attempt, attempts
            )
            await asyncio.sleep(pause)
        except TelegramNetworkError as error:
            logger.warning("Bot API недоступен (%s), повтор через %.0f с (%s/%s)",
                           error, delay, attempt, attempts)
            await asyncio.sleep(delay)

    raise RuntimeError("Telegram Bot API не ответил за отведённое время")


async def escrow_finalizer(bot: Bot, repos: Repositories, interval: float = 60.0) -> None:
    """Раз в минуту закрывает сделки с истёкшим Trade Protection и напоминает о скором закрытии."""
    from bot.services.trades import finalize_due

    while True:
        await asyncio.sleep(interval)
        try:
            # напоминания: защита истекает в ближайшие сутки, участники ещё не предупреждены
            for trade in await repos.trades.list_holding_remindable(within_hours=24):
                marked = False
                for user_id in {trade["buyer_id"], trade["seller_id"]}:
                    user = await repos.users.get_by_id(user_id)
                    if not user:
                        continue
                    try:
                        await bot.send_message(
                            user["telegram_id"],
                            "Trade Protection по сделке #%d закроется в ближайшие сутки. "
                            "Если всё в порядке — дождитесь автозакрытия, иначе откройте спор." % trade["id"],
                        )
                        marked = True
                    except Exception:
                        logger.warning("Не удалось напомнить %s о сделке #%d", user["telegram_id"], trade["id"])
                if marked:
                    await repos.trades.mark_holding_reminded(trade["id"])

            # автоснятие объявлений с истёкшим сроком
            for offer in await repos.offers.list_expired_active():
                await repos.offers.update_status(offer["id"], "expired")
                owner = await repos.users.get_by_id(offer["creator_id"])
                if owner and bot:
                    try:
                        await bot.send_message(
                            owner["telegram_id"],
                            "Объявление «%s» снято — истёк срок. Продлить можно повторной публикацией." % offer["title"],
                        )
                    except Exception:
                        pass

            for trade in await repos.trades.list_holding_due():
                closed = await finalize_due(repos, trade)
                if not closed:
                    continue
                for user_id in {trade["buyer_id"], trade["seller_id"]}:
                    user = await repos.users.get_by_id(user_id)
                    if not user:
                        continue
                    try:
                        await bot.send_message(
                            user["telegram_id"],
                            "Trade Protection завершён — сделка закрыта. "
                            "Не забудьте оценить партнёра!",
                        )
                    except Exception:
                        logger.warning("Не удалось уведомить %s о закрытии сделки", user["telegram_id"])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка в escrow_finalizer")


def create_dispatcher(config: BotConfig) -> Dispatcher:
    """Собрать диспетчер с роутерами (используется и в тестах)."""
    dispatcher = Dispatcher(
        storage=SQLiteStorage("data/fsm.db"),
    )
    for router in ROUTERS:
        dispatcher.include_router(router)
    return dispatcher


async def main() -> None:
    config = load_config()
    log_llm_status(load_llm_config())
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

    me = await wait_for_telegram(bot)
    logger.info("Бот запущен: @%s", me.username)
    escrow_task = asyncio.create_task(escrow_finalizer(bot, repos))
    try:
        await dispatcher.start_polling(bot)
    finally:
        escrow_task.cancel()
        try:
            await escrow_task
        except asyncio.CancelledError:
            pass
        await close_price_fetcher()
        await close_steam_client()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
