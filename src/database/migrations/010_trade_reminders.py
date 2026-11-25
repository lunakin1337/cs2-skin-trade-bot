"""Миграция 010: отметка о напоминании по зависшей сделке."""

TRADE_COLUMNS = {
    "reminded_at": "TEXT",
}


async def _column_names(db, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cur.fetchall()}


async def upgrade(db) -> None:
    """Добавить trades.reminded_at: когда бот уже напомнил о сделке."""
    existing = await _column_names(db, "trades")
    for name, ddl in TRADE_COLUMNS.items():
        if name not in existing:
            await db.execute(f"ALTER TABLE trades ADD COLUMN {name} {ddl}")
    await db.commit()


async def downgrade(db) -> None:
    # Колонку не удаляем (как 003, 008, 009): терять нечего.
    await db.execute("UPDATE trades SET reminded_at = NULL")
    await db.commit()
