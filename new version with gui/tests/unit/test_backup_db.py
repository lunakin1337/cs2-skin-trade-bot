"""Резервные копии базы: создание, проверка содержимого, ротация."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import backup_db  # noqa: E402


def make_db(path: Path, rows: int) -> Path:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany("INSERT INTO users (name) VALUES (?)", [(f"u{i}",) for i in range(rows)])
    return path


def test_backup_copies_data(tmp_path):
    db = make_db(tmp_path / "bot.db", 3)

    report = backup_db.run(db, tmp_path / "backups", keep=7)

    copy = Path(report["created"])
    assert copy.exists()
    with sqlite3.connect(copy) as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert count == 3


def test_prune_keeps_newest(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir()
    for name in ["bot-20260101-000000.db", "bot-20260102-000000.db", "bot-20260103-000000.db"]:
        (directory / name).write_text("x", encoding="utf-8")
    db = make_db(tmp_path / "bot.db", 1)

    report = backup_db.run(db, directory, keep=2)

    names = sorted(path.name for path in backup_db.existing_backups(directory))
    assert len(names) == 2
    assert "bot-20260101-000000.db" in report["removed"]
    assert all("20260101" not in name for name in names)


def test_missing_database_raises(tmp_path):
    try:
        backup_db.make_backup(tmp_path / "nope.db", tmp_path / "backups")
    except FileNotFoundError as error:
        assert "nope.db" in str(error)
    else:
        raise AssertionError("ожидали FileNotFoundError")


def test_list_mode_handles_empty_directory(tmp_path, capsys):
    argv = sys.argv
    sys.argv = ["backup_db.py", "--dir", str(tmp_path / "none"), "--list"]
    try:
        assert backup_db.main() == 0
    finally:
        sys.argv = argv
    assert "копий нет" in capsys.readouterr().out
