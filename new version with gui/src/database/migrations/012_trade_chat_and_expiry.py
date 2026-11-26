"""Миграция 012: чат сделки и срок жизни объявления."""

TRADE_COLUMNS = {
    # (не используется: сообщения — отдельная таблица)
}

OFFER_COLUMNS = {
    "expires_at": "TEXT",
}


async def _column_names(db, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cur.fetchall()}


async def upgrade(db) -> None:
    """Сообщения сделки (новая таблица) и expires_at у объявлений."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (trade_id) REFERENCES trades(id),
            FOREIGN KEY (sender_id) REFERENCES users(id)
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_trade_messages_trade ON trade_messages(trade_id, created_at)"
    )

    offers_columns = await _column_names(db, "offers")
    for name, ddl in OFFER_COLUMNS.items():
        if name not in offers_columns:
            await db.execute(f"ALTER TABLE offers ADD COLUMN {name} {ddl}")
    await db.commit()


async def downgrade(db) -> None:
    await db.execute("DROP TABLE IF EXISTS trade_messages")
    await db.commit()
