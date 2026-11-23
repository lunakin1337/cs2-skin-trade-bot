"""Тесты сделок: подтверждения, обмен, завершение, отмена и оценки."""

import pytest

from bot.handlers.ratings import cb_rate, cb_rate_menu
from bot.handlers.trade_flow import (
    cb_accept_offer,
    cb_trade_cancel,
    cb_trade_complete,
    cb_trade_confirm,
)
from tests.helpers import alerts, last_text, make_callback

BUYER_TG = 123456789
SELLER_TG = 987654321


@pytest.fixture
async def duo(repos):
    seller = await repos.users.create_or_update(
        telegram_id=SELLER_TG,
        username="seller",
        first_name="Seller",
    )
    buyer = await repos.users.create_or_update(
        telegram_id=BUYER_TG,
        username="buyer",
        first_name="Buyer",
    )
    trade_url = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcd"

    for participant in (seller, buyer):
        await repos.users.link_steam(
            participant["id"],
            "76561198000000000",
            trade_url,
            trade_partner="1",
            trade_token="abcd",
        )

    return buyer, seller


@pytest.fixture
async def trade(repos, duo):
    buyer, seller = duo
    offer_id = await repos.offers.create(
        creator_id=seller["id"],
        title="AK-47 за кейсы",
        items_offered=[],
        items_wanted="кейсы",
    )
    trade_id = await repos.trades.create(
        buyer_id=buyer["id"],
        seller_id=seller["id"],
        offer_id=offer_id,
    )
    await repos.offers.update_status(offer_id, "in_trade")
    return trade_id


class TestConfirmations:
    async def test_single_side_keeps_pending(self, bot, repos, trade, session):
        await cb_trade_confirm(make_callback(bot, f"trade_confirm_{trade}", BUYER_TG), repos)

        record = await repos.trades.get_by_id(trade)
        assert record["buyer_confirmed_at"] is not None
        assert record["seller_confirmed_at"] is None
        assert record["status"] == "pending"
        assert any("второй стороны" in alert for alert in alerts(session))

    async def test_both_sides_move_to_escrow(self, bot, repos, trade):
        await cb_trade_confirm(make_callback(bot, f"trade_confirm_{trade}", BUYER_TG), repos)
        await cb_trade_confirm(make_callback(bot, f"trade_confirm_{trade}", SELLER_TG), repos)

        record = await repos.trades.get_by_id(trade)
        assert record["status"] == "in_escrow"

    async def test_outsider_cannot_confirm(self, bot, repos, trade, session):
        await cb_trade_confirm(make_callback(bot, f"trade_confirm_{trade}", 555555555), repos)

        record = await repos.trades.get_by_id(trade)
        assert record["buyer_confirmed_at"] is None
        assert any("не ваша сделка" in alert for alert in alerts(session))


class TestCompletion:
    async def test_both_sides_complete_trade(self, bot, repos, trade, duo):
        buyer, seller = duo

        for telegram_id in (BUYER_TG, SELLER_TG):
            await cb_trade_confirm(make_callback(bot, f"trade_confirm_{trade}", telegram_id), repos)
        for telegram_id in (BUYER_TG, SELLER_TG):
            await cb_trade_complete(make_callback(bot, f"trade_complete_{trade}", telegram_id), repos)

        record = await repos.trades.get_by_id(trade)
        assert record["status"] == "completed"
        assert record["completed_at"] is not None

        buyer_after = await repos.users.get_by_id(buyer["id"])
        seller_after = await repos.users.get_by_id(seller["id"])
        assert buyer_after["trades_count"] == 1
        assert seller_after["trades_count"] == 1

        offer = await repos.offers.get_by_id(record["offer_id"])
        assert offer["status"] == "completed"

    async def test_cannot_complete_before_confirm(self, bot, repos, trade, session):
        await cb_trade_complete(make_callback(bot, f"trade_complete_{trade}", BUYER_TG), repos)

        record = await repos.trades.get_by_id(trade)
        assert record["status"] == "pending"
        assert any("не готова" in alert for alert in alerts(session))


class TestCancellation:
    async def test_cancel_returns_offer_to_market(self, bot, repos, trade, session):
        record = await repos.trades.get_by_id(trade)

        await cb_trade_cancel(make_callback(bot, f"trade_cancel_{trade}", BUYER_TG), repos)

        updated = await repos.trades.get_by_id(trade)
        assert updated["status"] == "cancelled"

        offer = await repos.offers.get_by_id(record["offer_id"])
        assert offer["status"] == "active"
        assert any("отменена" in alert for alert in alerts(session))


class TestRatings:
    async def test_rating_updates_counterparty(self, bot, repos, trade, duo):
        buyer, seller = duo

        for telegram_id in (BUYER_TG, SELLER_TG):
            await cb_trade_confirm(make_callback(bot, f"trade_confirm_{trade}", telegram_id), repos)
        for telegram_id in (BUYER_TG, SELLER_TG):
            await cb_trade_complete(make_callback(bot, f"trade_complete_{trade}", telegram_id), repos)

        await cb_rate(make_callback(bot, f"rate_{trade}_5", BUYER_TG), repos)

        ratings = await repos.ratings.get_for_user(seller["id"])
        assert len(ratings) == 1
        assert ratings[0]["score"] == 5

        seller_after = await repos.users.get_by_id(seller["id"])
        assert seller_after["rating"] == 5.0

    async def test_duplicate_rating_rejected(self, bot, repos, trade, duo, session):
        for telegram_id in (BUYER_TG, SELLER_TG):
            await cb_trade_confirm(make_callback(bot, f"trade_confirm_{trade}", telegram_id), repos)
        for telegram_id in (BUYER_TG, SELLER_TG):
            await cb_trade_complete(make_callback(bot, f"trade_complete_{trade}", telegram_id), repos)

        await cb_rate(make_callback(bot, f"rate_{trade}_5", BUYER_TG), repos)
        await cb_rate(make_callback(bot, f"rate_{trade}_1", BUYER_TG), repos)

        seller = await repos.users.get_by_telegram_id(SELLER_TG)
        ratings = await repos.ratings.get_for_user(seller["id"])
        assert len(ratings) == 1
        assert ratings[0]["score"] == 5
        assert any("уже оценили" in alert for alert in alerts(session))

    async def test_rate_menu_only_for_completed(self, bot, repos, trade, session):
        await cb_rate_menu(make_callback(bot, f"rate_menu_{trade}", BUYER_TG), repos)

        assert any("завершённую" in alert for alert in alerts(session))


class TestAcceptOffer:
    async def test_buyer_creates_trade(self, bot, repos, duo, session):
        buyer, seller = duo
        offer_id = await repos.offers.create(
            creator_id=seller["id"],
            title="M4A1-S",
            items_offered=[],
            items_wanted="AWP",
        )

        await cb_accept_offer(make_callback(bot, f"accept_offer_{offer_id}", BUYER_TG), repos)

        trades = await repos.trades.get_by_user(buyer["id"])
        assert len(trades) == 1
        assert trades[0]["seller_id"] == seller["id"]
        assert "сделка" in last_text(session)

        offer = await repos.offers.get_by_id(offer_id)
        assert offer["status"] == "in_trade"
