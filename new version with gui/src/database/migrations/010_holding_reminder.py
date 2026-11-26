"""Миграция 010: напоминание о сделке в holding до окончания Trade Protection."""

TRADE_COLUMNS = {
    "reminder_sent_at": "TEXT",
}


async def _column_names(db, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cur.fetchall()}


async def upgrade(db) -> None:
    """Добавить reminder_sent_at: когда участникам уже отправляли напоминание."""
    existing = await _column_names(db, "trades")
    for name, ddl in TRADE_COLUMNS.items():
        if name not in existing:
            await db.execute(f"ALTER TABLE trades ADD COLUMN {name} {ddl}")
    await db.commit()


async def downgrade(db) -> None:
    # Колонку не удаляем (как в 003/008): просто сбрасываем флаг.
    await db.execute("UPDATE trades SET reminder_sent_at = NULL")
    await db.commit()
