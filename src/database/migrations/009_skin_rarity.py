"""Миграция 009: редкость скина прямо в каталоге.

Раньше редкость бралась только из инвентарей (`items.rarity`), поэтому у скинов,
которых ни у кого нет, цвет редкости в каталоге отсутствовал.
"""

SKIN_COLUMNS = {
    "rarity": "TEXT",
}


async def _column_names(db, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cur.fetchall()}


async def upgrade(db) -> None:
    """Добавить skins.rarity (слаг CS2: consumer…covert, rare, contraband)."""
    existing = await _column_names(db, "skins")
    for name, ddl in SKIN_COLUMNS.items():
        if name not in existing:
            await db.execute(f"ALTER TABLE skins ADD COLUMN {name} {ddl}")
    await db.execute(
        """
        UPDATE skins
        SET rarity = (
            SELECT MAX(items.rarity) FROM items
            WHERE items.market_hash_name = skins.market_hash_name AND items.rarity IS NOT NULL
        )
        WHERE rarity IS NULL
        """
    )
    await db.commit()


async def downgrade(db) -> None:
    # Колонку оставляем (как 003 и 008): терять данные не за что.
    await db.execute("UPDATE skins SET rarity = NULL")
    await db.commit()
