"""Миграция 008: Trade Protection — срок окончательного закрытия сделки."""

TRADE_COLUMNS = {
    "finalize_at": "TEXT",
}


async def _column_names(db, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cur.fetchall()}


async def upgrade(db) -> None:
    """Добавить finalize_at: когда сделка станет окончательной (обмен + 7 дней)."""
    existing = await _column_names(db, "trades")
    for name, ddl in TRADE_COLUMNS.items():
        if name not in existing:
            await db.execute(f"ALTER TABLE trades ADD COLUMN {name} {ddl}")
    await db.commit()


async def downgrade(db) -> None:
    # Колонку не удаляем (как и 003): переводим ждущие сделки назад в обмен.
    await db.execute(
        "UPDATE trades SET status = 'in_escrow', finalize_at = NULL WHERE status = 'holding'"
    )
    await db.commit()
