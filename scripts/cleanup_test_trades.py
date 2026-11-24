"""Чистка мусорных тестовых сделок.

Мусор — сделки, где одна из сторон бот: Telegram id из --bot-id (по умолчанию сам
бот 9142832309) или username, оканчивающийся на «bot» (обычным пользователям Telegram
такие имена недоступны). Вместе со сделками уходят их trade_items, ratings и disputes,
объявления ботов, а объявления живых людей, зависшие в статусе in_trade только из-за
удалённых сделок, возвращаются на доску (active).

По умолчанию — dry-run: только печатает, что будет удалено. С --apply сначала делает
резервную копию базы рядом с ней (data/bot-cleanup-<время>.db.bak), затем удаляет всё
одной транзакцией.

    python scripts/cleanup_test_trades.py                 # dry-run по data/bot.db
    python scripts/cleanup_test_trades.py --apply         # бэкап + удаление
"""

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DEFAULT_BOT_IDS = (9142832309,)


@dataclass
class CleanupPlan:
    bot_users: list[dict] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    trade_items: list[dict] = field(default_factory=list)
    ratings: list[dict] = field(default_factory=list)
    disputes: list[dict] = field(default_factory=list)
    offers_delete: list[dict] = field(default_factory=list)
    offers_reactivate: list[dict] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (
            self.trades or self.trade_items or self.ratings or self.disputes
            or self.offers_delete or self.offers_reactivate
        )


def _rows(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def _in(ids: list[int]) -> str:
    return ",".join("?" * len(ids))


def build_plan(conn: sqlite3.Connection, bot_ids: tuple[int, ...] = DEFAULT_BOT_IDS) -> CleanupPlan:
    plan = CleanupPlan()
    plan.bot_users = _rows(
        conn,
        f"SELECT id, telegram_id, username FROM users "
        f"WHERE telegram_id IN ({_in(list(bot_ids))}) OR lower(username) LIKE '%bot' "
        "ORDER BY id",
        tuple(bot_ids),
    )
    bot_user_ids = [user["id"] for user in plan.bot_users]
    if not bot_user_ids:
        return plan

    marks = _in(bot_user_ids)
    plan.trades = _rows(
        conn,
        f"SELECT id, buyer_id, seller_id, offer_id, status, created_at FROM trades "
        f"WHERE buyer_id IN ({marks}) OR seller_id IN ({marks}) ORDER BY id",
        tuple(bot_user_ids) * 2,
    )
    plan.offers_delete = _rows(
        conn,
        f"SELECT id, creator_id, title, status FROM offers WHERE creator_id IN ({marks}) ORDER BY id",
        tuple(bot_user_ids),
    )

    trade_ids = [trade["id"] for trade in plan.trades]
    if trade_ids:
        trade_marks = _in(trade_ids)
        for name in ("trade_items", "ratings", "disputes"):
            setattr(
                plan,
                name,
                _rows(conn, f"SELECT * FROM {name} WHERE trade_id IN ({trade_marks}) ORDER BY id",
                      tuple(trade_ids)),
            )

        deleted_offers = {offer["id"] for offer in plan.offers_delete}
        plan.offers_reactivate = _rows(
            conn,
            f"""
            SELECT o.id, o.creator_id, o.title, o.status FROM offers o
            WHERE o.status = 'in_trade'
              AND o.id IN (SELECT offer_id FROM trades WHERE id IN ({trade_marks}))
              AND NOT EXISTS (
                  SELECT 1 FROM trades t
                  WHERE t.offer_id = o.id
                    AND t.id NOT IN ({trade_marks})
                    AND t.status IN ('pending', 'confirmed', 'in_escrow')
              )
            ORDER BY o.id
            """,
            tuple(trade_ids) * 2,
        )
        plan.offers_reactivate = [
            offer for offer in plan.offers_reactivate if offer["id"] not in deleted_offers
        ]

    return plan


def format_plan(plan: CleanupPlan) -> str:
    lines = []
    users = ", ".join(
        f"#{user['id']} tg={user['telegram_id']} @{user['username'] or '—'}" for user in plan.bot_users
    )
    lines.append(f"Боты в users: {users or 'нет'}")
    lines.append(f"Сделки к удалению: {len(plan.trades)}")
    lines.extend(
        f"  trade #{t['id']}: buyer={t['buyer_id']} seller={t['seller_id']} "
        f"offer={t['offer_id']} status={t['status']} created={t['created_at']}"
        for t in plan.trades
    )
    lines.append(f"trade_items к удалению: {len(plan.trade_items)}")
    lines.extend(
        f"  trade_item #{i['id']}: trade={i['trade_id']} item={i['item_id']} "
        f"{i['from_user_id']}→{i['to_user_id']}"
        for i in plan.trade_items
    )
    lines.append(f"ratings к удалению: {len(plan.ratings)}")
    lines.extend(
        f"  rating #{r['id']}: trade={r['trade_id']} {r['from_user_id']}→{r['to_user_id']} score={r['score']}"
        for r in plan.ratings
    )
    lines.append(f"disputes к удалению: {len(plan.disputes)}")
    lines.extend(
        f"  dispute #{d['id']}: trade={d['trade_id']} status={d['status']}" for d in plan.disputes
    )
    lines.append(f"Объявления ботов к удалению: {len(plan.offers_delete)}")
    lines.extend(
        f"  offer #{o['id']}: creator={o['creator_id']} status={o['status']} «{o['title']}»"
        for o in plan.offers_delete
    )
    lines.append(f"Объявления вернуть на доску (in_trade → active): {len(plan.offers_reactivate)}")
    lines.extend(
        f"  offer #{o['id']}: creator={o['creator_id']} «{o['title']}»" for o in plan.offers_reactivate
    )
    return "\n".join(lines)


def backup_database(conn: sqlite3.Connection, db_path: Path) -> Path:
    """Онлайн-копия через sqlite backup API — консистентна даже при работающем боте."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = db_path.with_name(f"{db_path.stem}-cleanup-{stamp}.db.bak")
    with sqlite3.connect(target) as backup:
        conn.backup(backup)
    backup.close()
    return target


def apply_plan(conn: sqlite3.Connection, plan: CleanupPlan) -> None:
    trade_ids = [trade["id"] for trade in plan.trades]
    rated_users = {rating["to_user_id"] for rating in plan.ratings}
    completed_sides = [
        side for trade in plan.trades if trade["status"] == "completed"
        for side in (trade["buyer_id"], trade["seller_id"])
    ]

    with conn:
        if trade_ids:
            marks = _in(trade_ids)
            for table in ("ratings", "disputes", "trade_items"):
                conn.execute(f"DELETE FROM {table} WHERE trade_id IN ({marks})", tuple(trade_ids))
            conn.execute(f"DELETE FROM trades WHERE id IN ({marks})", tuple(trade_ids))
        for offer in plan.offers_delete:
            conn.execute("DELETE FROM offers WHERE id = ?", (offer["id"],))
        for offer in plan.offers_reactivate:
            conn.execute(
                "UPDATE offers SET status = 'active', updated_at = datetime('now') WHERE id = ?",
                (offer["id"],),
            )
        for user_id in completed_sides:
            conn.execute(
                "UPDATE users SET trades_count = MAX(trades_count - 1, 0) WHERE id = ?", (user_id,)
            )
        for user_id in rated_users:
            conn.execute(
                "UPDATE users SET rating = COALESCE((SELECT AVG(score) FROM ratings "
                "WHERE to_user_id = ?), 0) WHERE id = ?",
                (user_id, user_id),
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Удалить мусорные тестовые сделки (по умолчанию dry-run)")
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/bot.db"), help="Путь к SQLite")
    parser.add_argument(
        "--bot-id", type=int, action="append", dest="bot_ids",
        help="Telegram id бота (можно несколько; по умолчанию 9142832309)",
    )
    parser.add_argument("--apply", action="store_true", help="Сделать бэкап и удалить")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"База не найдена: {db_path}", file=sys.stderr)
        return 1

    mode = "rw" if args.apply else "ro"
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode={mode}", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        plan = build_plan(conn, tuple(args.bot_ids or DEFAULT_BOT_IDS))
        print(format_plan(plan))
        if plan.empty:
            print("\nУдалять нечего.")
            return 0
        if not args.apply:
            print("\nDry-run: ничего не изменено. Для удаления запустите с --apply.")
            return 0

        backup = backup_database(conn, db_path)
        print(f"\nБэкап: {backup}")
        apply_plan(conn, plan)
        print("Готово: записи удалены.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
