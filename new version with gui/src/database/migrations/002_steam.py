"""Миграция 002: поля Steam — профиль, trade URL, данные инвентаря."""

USER_COLUMNS = {
    "steam_persona": "TEXT",
    "steam_avatar_url": "TEXT",
    "steam_profile_url": "TEXT",
    "steam_trade_partner": "TEXT",
    "steam_trade_token": "TEXT",
    "steam_linked_at": "TEXT",
    "inventory_synced_at": "TEXT",
}

ITEM_COLUMNS = {
    "class_id": "TEXT",
    "instance_id": "TEXT",
    "icon_url": "TEXT",
    "is_marketable": "INTEGER DEFAULT 1",
    "synced_at": "TEXT",
}


async def _column_names(db, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return {row["name"] for row in rows}


async def _add_columns(db, table: str, columns: dict[str, str]) -> None:
    existing = await _column_names(db, table)
    for name, ddl in columns.items():
        if name not in existing:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


async def upgrade(db) -> None:
    """Добавить поля Steam и уникальность предметов инвентаря."""
    await _add_columns(db, "users", USER_COLUMNS)
    await _add_columns(db, "items", ITEM_COLUMNS)

    # Дубли по (owner_id, steam_asset_id) ломают индекс — оставляем самую свежую запись.
    await db.execute(
        """
        DELETE FROM items
        WHERE id NOT IN (
            SELECT MAX(id) FROM items GROUP BY owner_id, steam_asset_id
        )
        """
    )
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_items_owner_asset ON items(owner_id, steam_asset_id)"
    )
    await db.commit()


async def downgrade(db) -> None:
    """Откат: снимаем индекс. Колонки SQLite не удаляет без пересоздания таблицы."""
    await db.execute("DROP INDEX IF EXISTS idx_items_owner_asset")
    await db.commit()
