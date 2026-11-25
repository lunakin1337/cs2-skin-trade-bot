"""Напоминания по зависшим сделкам: находятся, отправляются один раз, помечаются."""

import pytest

from bot.services.reminders import remind_stale_trades


@pytest.fixture
async def stale_trade(repos):
    seller = await repos.users.create_or_update(telegram_id=550001, username="seller")
    buyer = await repos.users.create_or_update(telegram_id=550002, username="buyer")
    trade = await repos.trades.create(buyer_id=buyer["id"], seller_id=seller["id"], offer_id=None)
    await repos.db.execute(
        "UPDATE trades SET created_at = datetime('now', '-40 minutes') WHERE id = ?", (trade,)
    )
    await repos.db.commit()
    return {"trade": trade, "seller": seller, "buyer": buyer}


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


async def test_stale_trade_is_reminded_once(repos, stale_trade):
    bot = FakeBot()

    first = await remind_stale_trades(bot, repos, minutes=15)
    second = await remind_stale_trades(bot, repos, minutes=15)

    assert first == 1
    assert second == 0
    assert sorted(chat_id for chat_id, _ in bot.sent) == [550001, 550002]
    assert all("ждёт подтверждения" in text for _, text in bot.sent)


async def test_fresh_trade_is_not_reminded(repos):
    seller = await repos.users.create_or_update(telegram_id=550003, username="fresh_seller")
    buyer = await repos.users.create_or_update(telegram_id=550004, username="fresh_buyer")
    await repos.trades.create(buyer_id=buyer["id"], seller_id=seller["id"], offer_id=None)
    bot = FakeBot()

    assert await remind_stale_trades(bot, repos, minutes=15) == 0
    assert bot.sent == []


async def test_only_unconfirmed_side_is_reminded(repos, stale_trade):
    await repos.trades.set_confirmed(stale_trade["trade"], "seller")
    bot = FakeBot()

    assert await remind_stale_trades(bot, repos, minutes=15) == 1
    assert [chat_id for chat_id, _ in bot.sent] == [550002]


async def test_trade_has_reminded_at_column(repos, stale_trade):
    await repos.trades.mark_reminded(stale_trade["trade"])
    trade = await repos.trades.get_by_id(stale_trade["trade"])

    assert trade["reminded_at"] is not None
