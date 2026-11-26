"""Миграция 011: объявления «Ищут» — хотелки без выставленных скинов."""


async def _column_names(db, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cur.fetchall()}


async def upgrade(db) -> None:
    """Таблица хотелок: что ищет пользователь и в каком статусе объявление."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS wanted (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            skin_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_wanted_skin ON wanted(skin_name, status)"
    )
    await db.commit()


async def downgrade(db) -> None:
    await db.execute("DROP TABLE IF EXISTS wanted")
    await db.commit()
