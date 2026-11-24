"""Поиск скинов в каталоге по свободному описанию (общий для бота и Mini App)."""

import difflib

from bot.utils.skin_query import parse_query
from database.repository import Repositories

CANDIDATES = 3
FUZZY_THRESHOLD = 0.45


async def find_candidates(repos: Repositories, text: str, limit: int = CANDIDATES) -> list[dict]:
    """Ищет постепенно ослабляя условия: износ и цена могут отсутствовать в каталоге."""
    parsed = parse_query(text)
    if not parsed.tokens:
        return []

    attempts = [
        {"wear": parsed.wear, "max_price": parsed.max_price},
        {"wear": parsed.wear, "max_price": None},
        {"wear": None, "max_price": parsed.max_price},
        {"wear": None, "max_price": None},
    ]
    for attempt in attempts:
        found = await repos.skins.search_structured(
            parsed.tokens,
            wear=attempt["wear"],
            max_price=attempt["max_price"],
            stattrak=parsed.stattrak,
            limit=limit,
        )
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
