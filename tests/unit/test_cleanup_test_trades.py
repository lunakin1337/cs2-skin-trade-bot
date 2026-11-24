"""Тесты скрипта чистки тестовых сделок на временной базе."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from database import Repositories, init_database

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cleanup_test_trades.py"
BOT_TG = 9142832309


def _load_script():
    spec = importlib.util.spec_from_file_location("cleanup_test_trades", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cleanup = _load_script()


@pytest.fixture
async def seeded(tmp_path):
    """База: живая сделка людей + сделка с ботом-продавцом + сделка с @...bot."""
    db_path = tmp_path / "data" / "bot.db"
    db = await init_database(str(db_path))
    repos = Repositories(db)

    alice = await repos.users.create_or_update(telegram_id=111, username="alice")
    bob = await repos.users.create_or_update(telegram_id=222, username="bob")
    bot = await repos.users.create_or_update(telegram_id=BOT_TG)
    helper_bot = await repos.users.create_or_update(telegram_id=333, username="HelperBot")

    real_offer = await repos.offers.create(
        creator_id=bob["id"], title="real", items_offered=[], items_wanted="x"
    )
    real_trade = await repos.trades.create(alice["id"], bob["id"], real_offer)
    await repos.trade_items.add(real_trade, 1, bob["id"], alice["id"])
    await repos.trades.mark_completed(real_trade)
    await repos.ratings.create(real_trade, alice["id"], bob["id"], 5)

    bot_offer = await repos.offers.create(
        creator_id=bot["id"], title="bot knife", items_offered=[], items_wanted="x"
    )
    await repos.offers.update_status(bot_offer, "in_trade")
    bot_trade = await repos.trades.create(alice["id"], bot["id"], bot_offer)
    await repos.trade_items.add(bot_trade, 2, bot["id"], alice["id"])
    await repos.disputes.create(bot_trade, alice["id"], "тест")

    stuck_offer = await repos.offers.create(
        creator_id=bob["id"], title="stuck", items_offered=[], items_wanted="x"
    )
    await repos.offers.update_status(stuck_offer, "in_trade")
    helper_trade = await repos.trades.create(helper_bot["id"], bob["id"], stuck_offer)
    await repos.trades.mark_completed(helper_trade)
    await repos.ratings.create(helper_trade, helper_bot["id"], bob["id"], 1)
    await repos.users.increment_trades_count(bob["id"])
    await repos.users.increment_trades_count(bob["id"])
    await repos.users.recompute_rating(bob["id"])

    await db.close()
    return {
        "path": db_path,
        "real_trade": real_trade,
        "bot_trade": bot_trade,
        "helper_trade": helper_trade,
        "bot_offer": bot_offer,
        "stuck_offer": stuck_offer,
        "real_offer": real_offer,
        "bob": bob["id"],
    }


def _count(path: Path, query: str, params: tuple = ()) -> int:
    with sqlite3.connect(path) as conn:
        return conn.execute(query, params).fetchone()[0]


def test_dry_run_changes_nothing(seeded, capsys):
    before = _count(seeded["path"], "SELECT COUNT(*) FROM trades")

    assert cleanup.main(["--db", str(seeded["path"])]) == 0

    out = capsys.readouterr().out
    assert "Сделки к удалению: 2" in out
    assert f"trade #{seeded['bot_trade']}" in out
    assert f"trade #{seeded['helper_trade']}" in out
    assert f"trade #{seeded['real_trade']}:" not in out
    assert "Dry-run" in out
    assert _count(seeded["path"], "SELECT COUNT(*) FROM trades") == before
    assert not list(seeded["path"].parent.glob("*.bak"))


def test_plan_collects_related_rows(seeded):
    conn = sqlite3.connect(seeded["path"])
    conn.row_factory = sqlite3.Row
    plan = cleanup.build_plan(conn)
    conn.close()

    assert {t["id"] for t in plan.trades} == {seeded["bot_trade"], seeded["helper_trade"]}
    assert len(plan.trade_items) == 1
    assert len(plan.ratings) == 1
    assert len(plan.disputes) == 1
    assert [o["id"] for o in plan.offers_delete] == [seeded["bot_offer"]]
    assert [o["id"] for o in plan.offers_reactivate] == [seeded["stuck_offer"]]


def test_apply_backs_up_and_deletes(seeded, capsys):
    path = seeded["path"]

    assert cleanup.main(["--db", str(path), "--apply"]) == 0

    backups = list(path.parent.glob("bot-cleanup-*.db.bak"))
    assert len(backups) == 1
    assert _count(backups[0], "SELECT COUNT(*) FROM trades") == 3

    assert _count(path, "SELECT COUNT(*) FROM trades") == 1
    assert _count(path, "SELECT id FROM trades") == seeded["real_trade"]
    assert _count(path, "SELECT COUNT(*) FROM trade_items") == 1
    assert _count(path, "SELECT COUNT(*) FROM ratings") == 1
    assert _count(path, "SELECT COUNT(*) FROM disputes") == 0
    assert _count(path, "SELECT COUNT(*) FROM offers WHERE id = ?", (seeded["bot_offer"],)) == 0
    with sqlite3.connect(path) as conn:
        status = conn.execute(
            "SELECT status FROM offers WHERE id = ?", (seeded["stuck_offer"],)
        ).fetchone()[0]
        trades_count, rating = conn.execute(
            "SELECT trades_count, rating FROM users WHERE id = ?", (seeded["bob"],)
        ).fetchone()
    assert status == "active"
    assert trades_count == 1
    assert rating == 5.0

    assert cleanup.main(["--db", str(path)]) == 0
    assert "Удалять нечего" in capsys.readouterr().out


def test_missing_db(tmp_path):
    assert cleanup.main(["--db", str(tmp_path / "nope.db")]) == 1
