"""Тесты инициализации базы: каталог и миграции."""

from pathlib import Path

from database import init_database


class TestInitDatabase:
    async def test_creates_missing_directories(self, tmp_path):
        db_path = tmp_path / "nested" / "data" / "bot.db"

        db = await init_database(str(db_path))
        try:
            assert db_path.exists()

            cur = await db.execute("SELECT name FROM migrations ORDER BY id")
            applied = [row["name"] for row in await cur.fetchall()]
            assert applied == ["001_initial", "002_steam", "003_trade_flow"]
        finally:
            await db.close()

    async def test_reuses_existing_database(self, tmp_path):
        db_path = tmp_path / "bot.db"

        first = await init_database(str(db_path))
        await first.execute("INSERT INTO settings (key, value) VALUES ('k', 'v')")
        await first.commit()
        await first.close()

        second = await init_database(str(db_path))
        try:
            cur = await second.execute("SELECT value FROM settings WHERE key = 'k'")
            row = await cur.fetchone()
            assert row["value"] == "v"
        finally:
            await second.close()

        assert Path(db_path).exists()
