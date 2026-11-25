"""Заполнить редкость в каталоге скинов из открытого датасета CSGO-API.

Зачем: Steam Market не отдаёт редкость в каталоге напрямую (только цвет в
`asset_description.name_color` при импорте), поэтому у скинов, импортированных
раньше, редкости нет. Датасет ByMykel/CSGO-API перечисляет все скины CS2 с цветом
редкости, и по нему каталог заполняется офлайн, без запросов к Steam.

По умолчанию — только отчёт. С `--apply` пишет редкость в базу.
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot.utils.skin_categories import rarity_from_market  # noqa: E402
from database import init_database  # noqa: E402

logger = logging.getLogger("import_rarities")

DATASET_URL = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/skins.json"

WEAR_SUFFIX = re.compile(
    r"\s*\((Factory New|Minimal Wear|Field-Tested|Well-Worn|Battle-Scarred"
    r"|Прямо с завода|Немного поношенное|После полевых|Поношенное|Закалённое в боях)\)\s*$"
)
PREFIX = re.compile(r"^(StatTrak™?|Souvenir)\s+", re.I)


def base_name(market_hash_name: str) -> str:
    """«StatTrak™ AK-47 | Redline (FT)» -> «AK-47 | Redline»."""
    name = WEAR_SUFFIX.sub("", (market_hash_name or "").strip())
    return PREFIX.sub("", name).strip()


def build_rarity_map(skins: list[Dict[str, Any]]) -> Dict[str, str]:
    """Имя без износа -> слаг редкости. Первое совпадение побеждает."""
    mapping: Dict[str, str] = {}
    for skin in skins or []:
        name = (skin.get("name") or "").strip()
        if not name:
            continue
        rarity = skin.get("rarity") or {}
        slug = rarity_from_market(rarity.get("color"), rarity.get("name"), name)
        if slug and name not in mapping:
            mapping[name] = slug
    return mapping


async def load_dataset(source: str) -> list[Dict[str, Any]]:
    if source.startswith(("http://", "https://")):
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(source) as response:
                response.raise_for_status()
                return await response.json(content_type=None)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def resolve(mapping: Dict[str, str], market_hash_name: str) -> str | None:
    """Редкость для имени из каталога: сначала точное имя, затем без префиксов и износа."""
    if market_hash_name in mapping:
        return mapping[market_hash_name]
    return mapping.get(base_name(market_hash_name))


async def run(source: str, db_path: str, apply: bool) -> Dict[str, Any]:
    dataset = await load_dataset(source)
    mapping = build_rarity_map(dataset)
    logger.info("Датасет: %s скинов, редкость известна для %s", len(dataset), len(mapping))

    db = await init_database(db_path)
    try:
        cur = await db.execute("SELECT market_hash_name, rarity FROM skins")
        rows = await cur.fetchall()

        updates: list[tuple[str, str]] = []
        unknown: list[str] = []
        for row in rows:
            name = row["market_hash_name"]
            found = resolve(mapping, name)
            if not found:
                unknown.append(name)
                continue
            if row["rarity"] != found:
                updates.append((found, name))

        by_rarity: Dict[str, int] = {}
        for rarity, _ in updates:
            by_rarity[rarity] = by_rarity.get(rarity, 0) + 1

        report = {
            "catalog": len(rows),
            "dataset": len(mapping),
            "to_update": len(updates),
            "unknown": len(unknown),
            "by_rarity": dict(sorted(by_rarity.items(), key=lambda pair: -pair[1])),
            "applied": False,
        }
        if not apply:
            return report

        for rarity, name in updates:
            await db.execute(
                "UPDATE skins SET rarity = ?, updated_at = datetime('now') WHERE market_hash_name = ?",
                (rarity, name),
            )
        await db.commit()
        report["applied"] = True
        return report
    finally:
        await db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Заполнить редкость каталога из CSGO-API")
    parser.add_argument("--source", default=DATASET_URL, help="URL или путь к skins.json")
    parser.add_argument("--db", default="data/bot.db", help="путь к базе")
    parser.add_argument("--apply", action="store_true", help="записать в базу (по умолчанию dry-run)")
    args = parser.parse_args()

    report = asyncio.run(run(args.source, args.db, args.apply))
    for key, value in report.items():
        print(f"{key}: {value}")
    if not report["applied"]:
        print("Dry-run: база не изменена. Для записи запустите с --apply.")


if __name__ == "__main__":
    main()
