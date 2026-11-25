"""Скрипт заполнения редкости каталога из CSGO-API."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from import_rarities import base_name, build_rarity_map, resolve  # noqa: E402

DATASET = [
    {"name": "AK-47 | Neon Rider", "rarity": {"name": "Covert", "color": "#eb4b4b"}},
    {"name": "AWP | Asiimov", "rarity": {"name": "Covert", "color": "#eb4b4b"}},
    {"name": "★ Karambit | Doppler", "rarity": {"name": "Extraordinary", "color": "#eb4b4b"}},
    {"name": "P250 | Sand Dune", "rarity": {"name": "Consumer Grade", "color": "#b0c3d9"}},
    {"name": "Sticker | Titan", "rarity": {}},
]


def test_base_name_strips_prefix_and_wear():
    assert base_name("AK-47 | Neon Rider (Field-Tested)") == "AK-47 | Neon Rider"
    assert base_name("StatTrak™ AWP | Asiimov (Minimal Wear)") == "AWP | Asiimov"
    assert base_name("Souvenir AWP | Asiimov (Battle-Scarred)") == "AWP | Asiimov"
    assert base_name("★ Karambit | Doppler (Factory New)") == "★ Karambit | Doppler"
    assert base_name("AK-47 | Neon Rider (Закалённое в боях)") == "AK-47 | Neon Rider"


def test_build_rarity_map_uses_color_and_name():
    mapping = build_rarity_map(DATASET)

    assert mapping["AK-47 | Neon Rider"] == "covert"
    assert mapping["P250 | Sand Dune"] == "consumer"
    assert mapping["★ Karambit | Doppler"] == "rare"
    assert "Sticker | Titan" not in mapping


def test_resolve_matches_wear_and_stattrak():
    mapping = build_rarity_map(DATASET)

    assert resolve(mapping, "AK-47 | Neon Rider (Field-Tested)") == "covert"
    assert resolve(mapping, "StatTrak™ AWP | Asiimov (Well-Worn)") == "covert"
    assert resolve(mapping, "Sticker | Titan (Holo)") is None


def test_apply_updates_catalog(tmp_path):
    import asyncio
    import json

    from database.migrations.migrate import init_database

    import import_rarities

    db_path = str(tmp_path / "catalog.db")
    source = tmp_path / "skins.json"
    source.write_text(json.dumps(DATASET), encoding="utf-8")

    async def seed():
        db = await init_database(db_path)
        try:
            await db.execute(
                "INSERT INTO skins (market_hash_name, name) VALUES (?, ?)",
                ("AK-47 | Neon Rider (Field-Tested)", "AK-47 | Neon Rider"),
            )
            await db.execute(
                "INSERT INTO skins (market_hash_name, name) VALUES (?, ?)",
                ("Glove Case", "Glove Case"),
            )
            await db.commit()
        finally:
            await db.close()

    asyncio.run(seed())
    dry = asyncio.run(import_rarities.run(str(source), db_path, False))
    assert dry["to_update"] == 1 and dry["applied"] is False and dry["unknown"] == 1

    real = asyncio.run(import_rarities.run(str(source), db_path, True))
    assert real["applied"] is True

    async def read():
        db = await init_database(db_path)
        try:
            cur = await db.execute("SELECT market_hash_name, rarity FROM skins ORDER BY id")
            return [(row["market_hash_name"], row["rarity"]) for row in await cur.fetchall()]
        finally:
            await db.close()

    assert asyncio.run(read()) == [
        ("AK-47 | Neon Rider (Field-Tested)", "covert"),
        ("Glove Case", None),
    ]
