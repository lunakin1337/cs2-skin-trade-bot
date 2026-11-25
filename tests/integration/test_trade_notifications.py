"""Уведомления по сделкам: обе стороны узнают о каждом шаге."""

import pytest

from bot.services import notifications
from tests.helpers import RecordingSession


@pytest.fixture
async def people(repos):
    seller = await repos.users.create_or_update(telegram_id=660001, username="seller")
    buyer = await repos.users.create_or_update(telegram_id=660002, username="buyer")
    item = await repos.items.add(
        owner_id=seller["id"], steam_asset_id="n1", market_hash_name="AWP | Asiimov (Field-Tested)"
    )
    offer = await repos.offers.create(
        creator_id=seller["id"],
        title="AWP | Asiimov → AUG | Sweeper",
        items_offered=[item],
        items_wanted="AUG | Sweeper",
        wanted_name="AUG | Sweeper (Field-Tested)",
    )
    trade = await repos.trades.create(buyer_id=buyer["id"], seller_id=seller["id"], offer_id=offer)
    return {"seller": seller, "buyer": buyer, "offer": offer, "trade": trade}


class FakeBot:
    def __init__(self):
        self.session = RecordingSession()

    async def send_message(self, chat_id, text, **kwargs):
        self.sent = getattr(self, "sent", [])
        self.sent.append((chat_id, text))
        return type("M", (), {"message_id": 1})()


async def test_new_trade_notifies_seller(repos, people):
    bot = FakeBot()

    await notifications.new_trade(bot, repos, await repos.trades.get_by_id(people["trade"]))

    assert len(bot.sent) == 1
    chat_id, text = bot.sent[0]
    assert chat_id == 660001
    assert "Новое предложение обмена" in text
    assert "@buyer" in text


async def test_both_confirmed_notifies_both(repos, people):
    bot = FakeBot()
    trade = await repos.trades.get_by_id(people["trade"])

    await notifications.both_confirmed(bot, repos, trade)

    chats = sorted(chat_id for chat_id, _ in bot.sent)
    assert chats == [660001, 660002]
    assert all("Steam Trade" in text for _, text in bot.sent)


async def test_side_received_notifies_other_side_only(repos, people):
    bot = FakeBot()
    trade = await repos.trades.get_by_id(people["trade"])

    await notifications.side_received(bot, repos, trade, people["buyer"]["id"])

    assert [chat_id for chat_id, _ in bot.sent] == [660001]
    assert "отметил" in bot.sent[0][1]


async def test_cancelled_notifies_counterparty(repos, people):
    bot = FakeBot()
    trade = await repos.trades.get_by_id(people["trade"])

    await notifications.cancelled(bot, repos, trade, people["buyer"]["id"])

    assert [chat_id for chat_id, _ in bot.sent] == [660001]
    assert "отменена" in bot.sent[0][1]


async def test_delivery_failure_does_not_raise(repos, people):
    class BrokenBot:
        async def send_message(self, *args, **kwargs):
            raise RuntimeError("бот заблокирован")

    trade = await repos.trades.get_by_id(people["trade"])

    assert await notifications.new_trade(BrokenBot(), repos, trade) is None


async def test_missing_telegram_id_skips_silently(repos, people, monkeypatch):
    bot = FakeBot()
    trade = await repos.trades.get_by_id(people["trade"])

    async def no_telegram_id(repos_arg, user_id):
        return None

    monkeypatch.setattr(notifications, "_telegram_id", no_telegram_id)

    await notifications.new_trade(bot, repos, trade)

    assert getattr(bot, "sent", []) == []
