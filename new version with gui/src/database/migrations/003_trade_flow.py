"""Миграция 003: двусторонние подтверждения сделки и оценки."""

TRADE_COLUMNS = {
    "buyer_confirmed_at": "TEXT",
    "seller_confirmed_at": "TEXT",
    "buyer_completed_at": "TEXT",
    "seller_completed_at": "TEXT",
}


async def _column_names(db, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cur.fetchall()}


async def upgrade(db) -> None:
    """Добавить отметки подтверждений и запретить дубли отзывов."""
    existing = await _column_names(db, "trades")
    for name, ddl in TRADE_COLUMNS.items():
        if name not in existing:
            await db.execute(f"ALTER TABLE trades ADD COLUMN {name} {ddl}")

    # Один отзыв на сделку от каждой стороны
    await db.execute(
        "DELETE FROM ratings WHERE id NOT IN ("
        "SELECT MAX(id) FROM ratings GROUP BY trade_id, from_user_id)"
    )
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ratings_trade_author ON ratings(trade_id, from_user_id)"
    )
    await db.commit()


async def downgrade(db) -> None:
    await db.execute("DROP INDEX IF EXISTS idx_ratings_trade_author")
    await db.commit()
