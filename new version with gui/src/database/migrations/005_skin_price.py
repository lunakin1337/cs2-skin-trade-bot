"""Миграция 005: числовая цена в каталоге скинов."""


async def _column_names(db, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cur.fetchall()}


async def upgrade(db) -> None:
    existing = await _column_names(db, "skins")
    if "price_value" not in existing:
        await db.execute("ALTER TABLE skins ADD COLUMN price_value REAL")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_skins_price ON skins(price_value)")
    await db.commit()


async def downgrade(db) -> None:
    await db.execute("DROP INDEX IF EXISTS idx_skins_price")
    await db.commit()
