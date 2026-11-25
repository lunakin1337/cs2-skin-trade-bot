"""Резервная копия базы бота через sqlite backup API с ротацией.

Копия консистентна даже при работающем боте: sqlite сам следит за блокировками,
поэтому останавливать поллинг не нужно.

    python scripts/backup_db.py                        # data/bot.db -> backups/, хранить 7
    python scripts/backup_db.py --keep 14 --dir D:/bk  # свой каталог и глубина
    python scripts/backup_db.py --list                 # что уже есть, без копирования
"""

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_DB = Path("data/bot.db")
DEFAULT_DIR = Path("backups")
DEFAULT_KEEP = 7
NAME_FMT = "bot-%Y%m%d-%H%M%S.db"


def existing_backups(directory: Path) -> list[Path]:
    """Копии в каталоге, от старых к новым (по имени — оно сортируется по времени)."""
    if not directory.exists():
        return []
    return sorted(directory.glob("bot-*.db"))


def make_backup(db_path: Path, directory: Path) -> Path:
    """Снять онлайн-копию базы и вернуть путь к файлу."""
    if not db_path.exists():
        raise FileNotFoundError(f"база не найдена: {db_path}")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / datetime.now().strftime(NAME_FMT)
    with sqlite3.connect(db_path) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    return target


def prune(directory: Path, keep: int) -> list[Path]:
    """Удалить старые копии, оставив `keep` самых свежих. Возвращает удалённые."""
    if keep < 1:
        return []
    backups = existing_backups(directory)
    extra = backups[: max(0, len(backups) - keep)]
    for path in extra:
        path.unlink(missing_ok=True)
    return extra


def run(db_path: Path, directory: Path, keep: int) -> dict:
    created = make_backup(db_path, directory)
    removed = prune(directory, keep)
    return {
        "created": str(created),
        "size_mb": round(created.stat().st_size / (1024 * 1024), 2),
        "removed": [path.name for path in removed],
        "kept": len(existing_backups(directory)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Резервная копия базы с ротацией")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="путь к базе")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="каталог копий")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="сколько копий хранить")
    parser.add_argument("--list", action="store_true", help="показать копии и выйти")
    args = parser.parse_args()

    if args.list:
        backups = existing_backups(args.dir)
        if not backups:
            print(f"В {args.dir} копий нет")
            return 0
        for path in backups:
            size = path.stat().st_size / (1024 * 1024)
            print(f"{path.name}  {size:.2f} МБ")
        return 0

    try:
        report = run(args.db, args.dir, args.keep)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Копия: {report['created']} ({report['size_mb']} МБ)")
    if report["removed"]:
        print("Удалены старые:", ", ".join(report["removed"]))
    print(f"Всего копий: {report['kept']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
