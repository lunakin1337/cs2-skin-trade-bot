"""Поиск скинов в каталоге по свободному описанию (общий для бота и Mini App)."""

import difflib
from typing import Optional

from bot.services.skin_query_llm import SkinQueryRefiner, get_refiner
from bot.utils.skin_query import SkinQuery, parse_query
from database.repository import Repositories

CANDIDATES = 3
FUZZY_THRESHOLD = 0.45


async def find_candidates(
    repos: Repositories,
    text: str,
    limit: int = CANDIDATES,
    refiner: Optional[SkinQueryRefiner] = None,
) -> list[dict]:
    """Ищет локально, а если ничего не нашлось — повторяет поиск по разбору модели."""
    parsed = parse_query(text)
    found = await _search_local(repos, parsed, limit) if parsed.tokens else []
    if found:
        return found

    refined = await _refine(text, refiner)
    if refined is None or not refined.tokens:
        return []
    return await _search_attempts(repos, refined, limit)


async def _search_local(repos: Repositories, parsed: SkinQuery, limit: int) -> list[dict]:
    """Разбор локального матчера: условия, категория, затем fuzzy по названиям."""
    found = await _search_attempts(repos, parsed, limit)
    if found:
        return found

    # «нож керамбит»: если ножей в каталоге нет, пробуем без категории, но без наклеек
    if "★" in parsed.tokens and len(parsed.tokens) > 1:
        relaxed = await repos.skins.search_structured(
            [token for token in parsed.tokens if token != "★"],
            wear=parsed.wear,
            max_price=parsed.max_price,
            limit=limit * 2,
        )
        weapons = [
            row
            for row in relaxed
            if not any(word in row["market_hash_name"] for word in ("Graffiti", "Sticker", "Capsule"))
        ]
        if weapons:
            return weapons[:limit]

    # опечатки и незнакомые сокращения — ближайшие названия с якорем из запроса
    names = await repos.skins.all_names()
    query = " ".join(parsed.tokens).lower()
    scored = difflib.get_close_matches(query, [name.lower() for name in names], n=limit, cutoff=FUZZY_THRESHOLD)
    if not scored:
        return []

    anchor = max(parsed.tokens, key=len)
    matched = []
    for needle in scored:
        for name in names:
            if name.lower() == needle:
                if anchor.lower() in name.lower():
                    matched.append({"market_hash_name": name, "price_text": None})
                break
    return matched


async def _search_attempts(repos: Repositories, parsed: SkinQuery, limit: int) -> list[dict]:
    """Ищет постепенно ослабляя условия: износ и цена могут отсутствовать в каталоге."""
    attempts = (
        (parsed.wear, parsed.max_price),
        (parsed.wear, None),
        (None, parsed.max_price),
        (None, None),
    )
    for wear, max_price in attempts:
        found = await repos.skins.search_structured(
            parsed.tokens,
            wear=wear,
            max_price=max_price,
            stattrak=parsed.stattrak,
            limit=limit,
        )
        if found:
            return found
    return []


async def _refine(text: str, refiner: Optional[SkinQueryRefiner]) -> Optional[SkinQuery]:
    instance = refiner if refiner is not None else get_refiner()
    if instance is None:
        return None
    return await instance.refine(text)
