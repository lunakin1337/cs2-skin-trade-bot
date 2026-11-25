"""Миграция 006: категории и оружие в каталоге скинов."""

import importlib

COLUMNS = {
    "category": "TEXT",
    "weapon": "TEXT",
}


async def _column_names(db, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cur.fetchall()}


async def upgrade(db) -> None:
    existing = await _column_names(db, "skins")
    for name, ddl in COLUMNS.items():
        if name not in existing:
            await db.execute(f"ALTER TABLE skins ADD COLUMN {name} {ddl}")

    await db.execute("CREATE INDEX IF NOT EXISTS idx_skins_category ON skins(category)")
    await db.commit()

    # разложить уже загруженный каталог по категориям
    classify_module = importlib.import_module("bot.utils.skin_categories")
    cur = await db.execute("SELECT id, market_hash_name FROM skins")
    rows = await cur.fetchall()
    for row in rows:
        category, weapon = classify_module.classify(row["market_hash_name"])
        await db.execute(
            "UPDATE skins SET category = ?, weapon = ? WHERE id = ?",
            (category, weapon, row["id"]),
        )
    await db.commit()


async def downgrade(db) -> None:
    await db.execute("DROP INDEX IF EXISTS idx_skins_category")
    await db.commit()
