"""Редкость в каталоге: цвет и тип из Steam Market, теги инвентаря, миграция."""

import pytest

from bot.utils.skin_categories import rarity_from_market, rarity_slug


@pytest.mark.parametrize(
    ("color", "type_text", "name", "expected"),
    [
        ("EB4B4B", "Covert Rifle", "AK-47 | Neon Rider", "covert"),
        ("8847FF", None, "AWP | Asiimov", "restricted"),
        ("#4B69FF", "Mil-Spec Grade Rifle", "M4A4 | Desolate Space", "milspec"),
        (None, "Classified Pistol", "USP-S | Kill Confirmed", "classified"),
        (None, "Extraordinary Gloves", "★ Sport Gloves | Vice", "rare"),
        (None, None, "★ Karambit | Doppler", "rare"),
        (None, "Graffiti", "Graffiti | Recoil", None),
        (None, None, "Sticker | Titan", None),
    ],
)
def test_rarity_from_market(color, type_text, name, expected):
    assert rarity_from_market(color, type_text, name) == expected


@pytest.mark.parametrize(
    ("tag", "name", "expected"),
    [
        ("Тайное", "AK-47 | Neon Rider", "covert"),
        ("Covert", "AWP | Asiimov", "covert"),
        ("Mil-Spec Grade", "M4A4 | Desolate Space", "milspec"),
        ("Засекреченное", "USP-S | Kill Confirmed", "classified"),
        ("Ширпотреб", "P250 | Sand Dune", "consumer"),
        (None, "★ Karambit | Doppler", "rare"),
        (None, "Sticker | Titan", None),
        ("", "Graffiti | Recoil", None),
    ],
)
def test_rarity_slug(tag, name, expected):
    assert rarity_slug(tag, name) == expected


def test_migration_fills_rarity_from_items(tmp_path):
    import asyncio

    from database.migrations.migrate import init_database

    db_path = str(tmp_path / "catalog.db")
    db = asyncio.run(init_database(db_path))
    try:
        cur = asyncio.run(db.execute("PRAGMA table_info(skins)"))
        columns = {row["name"] for row in asyncio.run(cur.fetchall())}
        assert "rarity" in columns
    finally:
        asyncio.run(db.close())


def test_catalog_import_row_carries_rarity():
    from bot.services.skin_catalog import _row

    skin = _row(
        {
            "hash_name": "AK-47 | Neon Rider (Field-Tested)",
            "name": "AK-47 | Neon Rider",
            "sell_price": 4500,
            "sell_price_text": "$45.00",
            "app_icon": "https://cdn/icon.png",
            "asset_description": {"name_color": "EB4B4B", "type": "Covert Rifle"},
        }
    )
    assert skin["rarity"] == "covert"
    assert skin["price_value"] == 45.0


def test_upsert_keeps_known_rarity_when_new_row_has_none():
    import asyncio

    from database.migrations.migrate import init_database
    from database.repository import SkinRepository

    async def scenario() -> tuple[str | None, str | None]:
        db = await init_database(":memory:")
        try:
            repo = SkinRepository(db)
            await repo.upsert_many([{"market_hash_name": "AWP | Asiimov (FT)", "rarity": "covert"}])
            await repo.upsert_many([{"market_hash_name": "AWP | Asiimov (FT)"}])
            cur = await db.execute("SELECT rarity FROM skins WHERE market_hash_name = ?", ("AWP | Asiimov (FT)",))
            kept = (await cur.fetchone())["rarity"]
            await repo.upsert_many([{"market_hash_name": "Sticker | Titan", "rarity": None}])
            cur = await db.execute("SELECT rarity FROM skins WHERE market_hash_name = ?", ("Sticker | Titan",))
            empty = (await cur.fetchone())["rarity"]
            return kept, empty
        finally:
            await db.close()

    assert asyncio.run(scenario()) == ("covert", None)
