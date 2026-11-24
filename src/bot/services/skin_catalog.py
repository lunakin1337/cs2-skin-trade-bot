"""Каталог скинов CS2: импорт из Steam Community Market и поиск."""

import argparse
import asyncio
import logging

import aiohttp

from database.repository import Repositories

logger = logging.getLogger(__name__)

MARKET_SEARCH_URL = "https://steamcommunity.com/market/search/render/"
PAGE_SIZE = 100
REQUEST_PAUSE = 2.0
RATE_LIMIT_PAUSE = 45
REQUEST_TIMEOUT = 20


def _row(result: dict) -> dict:
    name = (result.get("hash_name") or result.get("name") or "").strip()
    price_cents = result.get("sell_price")
    price_value = round(price_cents / 100, 2) if isinstance(price_cents, (int, float)) else None
    return {
        "market_hash_name": name,
        "name": result.get("name") or name,
        "price_text": (result.get("sell_price_text") or "").strip() or None,
        "price_value": price_value,
        "icon_url": result.get("app_icon"),
    }


async def import_catalog(repos: Repositories, pages: int = 30, query: str = "") -> int:
    """Загрузить каталог страницами по 100 позиций. Возвращает число записей."""
    imported = 0
    start = 0
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (compatible; CS2SkinTradeBot/0.2)"},
    ) as session:
        for page in range(pages):
            params = {
                "query": query,
                "start": start,
                "count": PAGE_SIZE,
                "search_descriptions": 0,
                "sort_column": "popular",
                "sort_dir": "desc",
                "appid": 730,
                "norender": 1,
            }
            try:
                async with session.get(MARKET_SEARCH_URL, params=params) as response:
                    if response.status == 429:
                        logger.info("Каталог: Steam придержал запросы, пауза %s с", RATE_LIMIT_PAUSE)
                        await asyncio.sleep(RATE_LIMIT_PAUSE)
                        continue
                    if response.status != 200:
                        logger.warning("Каталог: Steam ответил %s на странице %s", response.status, page)
                        break
                    data = await response.json(content_type=None)
            except (aiohttp.ClientError, ValueError) as error:
                logger.warning("Каталог: ошибка на странице %s — %s", page, error)
                break

            results = data.get("results") or []
            if not results:
                break

            imported += await repos.skins.upsert_many([_row(result) for result in results])
            # Steam отдаёт страницами по факту (обычно 10), поэтому шагаем на их размер
            start += len(results)
            logger.info("Каталог: запрос %s, всего %s", page + 1, imported)

            await asyncio.sleep(REQUEST_PAUSE)

    return imported


async def main() -> None:
    from config.settings import load_config
    from database import init_database

    parser = argparse.ArgumentParser(description="Импорт каталога скинов CS2")
    parser.add_argument("--pages", type=int, default=30, help="Сколько страниц по 100 брать")
    parser.add_argument("--query", default="", help="Поисковый запрос Steam Market")
    parser.add_argument("--db", default=None, help="Путь к базе (по умолчанию из .env)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db_path = args.db or load_config().db_path
    db = await init_database(db_path)
    try:
        total = await import_catalog(Repositories(db), pages=args.pages, query=args.query)
        print(f"в каталоге записей: {total}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
