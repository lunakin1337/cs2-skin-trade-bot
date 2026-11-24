"""Миграция 004: каталог скинов и структурированное «хочу» в предложениях."""

OFFER_COLUMNS = {
    "wanted_name": "TEXT",
}

SKIN_TABLE = """
CREATE TABLE IF NOT EXISTS skins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_hash_name TEXT NOT NULL UNIQUE,
    name TEXT,
    price_text TEXT,
    icon_url TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_skins_name ON skins(market_hash_name);
"""


async def _column_names(db, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cur.fetchall()}


async def upgrade(db) -> None:
    """Добавить каталог скинов и поле wanted_name у предложений."""
    await db.init_schema(SKIN_TABLE)

    existing = await _column_names(db, "offers")
    for name, ddl in OFFER_COLUMNS.items():
        if name not in existing:
            await db.execute(f"ALTER TABLE offers ADD COLUMN {name} {ddl}")

    await db.commit()


async def downgrade(db) -> None:
    await db.execute("DROP INDEX IF EXISTS idx_skins_name")
    await db.execute("DROP TABLE IF EXISTS skins")
    await db.commit()
