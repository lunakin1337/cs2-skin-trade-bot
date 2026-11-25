"""Миграция 007: не больше одного открытого спора на сделку."""


async def upgrade(db) -> None:
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_disputes_open_trade "
        "ON disputes(trade_id) WHERE status = 'open'"
    )
    await db.commit()


async def downgrade(db) -> None:
    await db.execute("DROP INDEX IF EXISTS idx_disputes_open_trade")
    await db.commit()
