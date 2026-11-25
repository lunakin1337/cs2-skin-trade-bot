"""Мигратор базы данных.

Схема живёт только здесь: каждый файл ``NNN_name.py`` — шаг вперёд (``upgrade``)
и назад (``downgrade``). Применённые шаги фиксируются в таблице ``migrations``.
"""

import argparse
import asyncio
import importlib
import logging

from pathlib import Path

from ..repository import Database

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent
MIGRATIONS_TABLE = "migrations"


async def ensure_migrations_table(db: Database) -> None:
    """Создать таблицу миграций, если её нет."""
    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.commit()


async def get_applied_migrations(db: Database) -> list[str]:
    cur = await db.execute(f"SELECT name FROM {MIGRATIONS_TABLE} ORDER BY id")
    rows = await cur.fetchall()
    return [row["name"] for row in rows]


def get_pending_migrations(applied: list[str]) -> list[tuple[str, object]]:
    pending = []
    for file in sorted(MIGRATIONS_DIR.glob("*.py")):
        if file.name in {"migrate.py", "__init__.py"}:
            continue
        name = file.stem
        if name not in applied:
            pending.append((name, importlib.import_module(f"database.migrations.{name}")))
    return pending


async def run_migrations(db: Database) -> list[str]:
    """Применить все ожидающие миграции, вернуть их имена."""
    await ensure_migrations_table(db)
    applied = await get_applied_migrations(db)
    pending = get_pending_migrations(applied)

    for name, module in pending:
        logger.info("Применяю миграцию %s", name)
        await module.upgrade(db)
        await db.execute(f"INSERT INTO {MIGRATIONS_TABLE} (name) VALUES (?)", (name,))
        await db.commit()

    return [name for name, _ in pending]


async def rollback_migration(db: Database, name: str) -> bool:
    """Откатить конкретную миграцию."""
    await ensure_migrations_table(db)
    if name not in await get_applied_migrations(db):
        logger.warning("Миграция %s не применена", name)
        return False

    module = importlib.import_module(f"database.migrations.{name}")
    await module.downgrade(db)
    await db.execute(f"DELETE FROM {MIGRATIONS_TABLE} WHERE name = ?", (name,))
    await db.commit()
    return True


async def init_database(db_path: str) -> Database:
    """Открыть соединение и довести схему до последней версии."""
    parent = Path(db_path).expanduser().parent
    parent.mkdir(parents=True, exist_ok=True)

    db = Database(db_path)
    await db.connect()
    await run_migrations(db)
    return db


async def main() -> None:
    parser = argparse.ArgumentParser(description="Database migrations")
    parser.add_argument("command", choices=["up", "down"])
    parser.add_argument("name", nargs="?", help="Имя миграции для down")
    parser.add_argument("--db", default="data/bot.db", help="Путь к базе")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    db = Database(args.db)
    await db.connect()
    try:
        if args.command == "up":
            await run_migrations(db)
        elif not args.name:
            parser.error("для down нужно имя миграции")
        else:
            await rollback_migration(db, args.name)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
