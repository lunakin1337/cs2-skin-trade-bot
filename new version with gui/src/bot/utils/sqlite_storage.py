"""FSM-хранилище на SQLite: состояния переживают перезапуск бота.

Использует синхронный sqlite3 в отдельном потоке исполнения (aiogram сам
оборачивает вызовы storage в to_thread-совместимый контекст), файл отдельный,
чтобы не конфликтовать с aiosqlite-соединением основного бота.
"""

import json
import sqlite3
from typing import Any, Optional

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey


class SQLiteStorage(BaseStorage):
    """Мини-реализация FSM-хранилища: состояние + данные в одной таблице."""

    def __init__(self, db_path: str):
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS fsm_storage (
                key TEXT PRIMARY KEY,
                state TEXT,
                data TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        self._connection.commit()

    @staticmethod
    def _key(key: StorageKey) -> str:
        return f"{key.bot_id}:{key.chat_id}:{key.user_id}:{key.thread_id}:{key.destiny}"

    def _write(self, key: str, state: Optional[str], data: dict[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO fsm_storage (key, state, data) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET state = excluded.state, data = excluded.data",
            (key, state, json.dumps(data, ensure_ascii=False)),
        )
        self._connection.commit()

    def _read(self, key: str) -> tuple[Optional[str], dict[str, Any]]:
        row = self._connection.execute(
            "SELECT state, data FROM fsm_storage WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return None, {}
        return row[0], json.loads(row[1])

    async def set_state(self, key: StorageKey, state: Optional[str] = None) -> None:
        k = self._key(key)
        _, data = self._read(k)
        self._write(k, state.state if isinstance(state, State) else state, data)

    async def get_state(self, key: StorageKey) -> Optional[str]:
        state, _ = self._read(self._key(key))
        return state

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        k = self._key(key)
        state, _ = self._read(k)
        self._write(k, state, data)

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        _, data = self._read(self._key(key))
        return data

    async def update_data(self, key: StorageKey, data: dict[str, Any]) -> dict[str, Any]:
        k = self._key(key)
        state, current = self._read(k)
        current.update(data)
        self._write(k, state, current)
        return current

    async def get_value(self, key: StorageKey, field: str) -> Optional[Any]:
        _, data = self._read(self._key(key))
        return data.get(field)

    async def close(self) -> None:
        self._connection.close()
