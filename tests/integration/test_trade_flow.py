"""Тесты сделок: подтверждения, обмен, холд Trade Protection, завершение, оценки."""

from datetime import datetime

import pytest

from bot.handlers.ratings import cb_rate, cb_rate_menu
from bot.handlers.trade_flow import (
    cb_accept_offer,
    cb_trade_cancel,
    cb_trade_complete,
    cb_trade_confirm,
    cb_trade_rollback,
)
from bot.handlers.trades import render_trades
from bot.services.trades import PROTECTION_DAYS, finalize_due
from bot.utils.formatters import format_deadline
from tests.helpers import alerts, last_text, make_callback

BUYER_TG = 123456789
SELLER_TG = 987654321


def _timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


async def _both_receive(bot, repos, trade_id: int) -> None:
    """Обе стороны подтверждают сделку и отмечают получение скинов."""
    for telegram_id in (BUYER_TG, SELLER_TG):
        await cb_trade_confirm(make_callback(bot, f"trade_confirm_{trade_id}", telegram_id), repos)
    for telegram_id in (BUYER_TG, SELLER_TG):
        await cb_trade_complete(make_callback(bot, f"trade_complete_{trade_id}", telegram_id), repos)


async def _expire_hold(repos, trade_id: int, offset: str = "-1 minute") -> dict:
    """Сдвинуть срок Trade Protection в прошлое и дать сделке закрыться ленивым переходом."""
    await repos.db.execute(
        f"UPDATE trades SET finalize_at = datetime('now', '{offset}') WHERE id = ?", (trade_id,)
    )
    await repos.db.commit()
    return await finalize_due(repos, await repos.trades.get_by_id(trade_id))


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
    async def test_both_sides_complete_moves_to_holding(self, bot, repos, trade, duo, session):
        buyer, seller = duo

        await _both_receive(bot, repos, trade)

        record = await repos.trades.get_by_id(trade)
        assert record["status"] == "holding"
        assert record["finalize_at"] is not None
        assert record["completed_at"] is None

        buyer_after = await repos.users.get_by_id(buyer["id"])
        seller_after = await repos.users.get_by_id(seller["id"])
        assert buyer_after["trades_count"] == 0
        assert seller_after["trades_count"] == 0

        offer = await repos.offers.get_by_id(record["offer_id"])
        assert offer["status"] == "in_trade"
        assert any("Trade Protection" in alert for alert in alerts(session))

    async def test_holding_finalizes_after_deadline(self, bot, repos, trade, duo):
        buyer, seller = duo

        await _both_receive(bot, repos, trade)
        holding = await repos.trades.get_by_id(trade)
        assert holding["status"] == "holding"

        record = await _expire_hold(repos, trade)
        assert record["status"] == "completed"
        assert record["completed_at"] == record["finalize_at"]

        buyer_after = await repos.users.get_by_id(buyer["id"])
        seller_after = await repos.users.get_by_id(seller["id"])
        assert buyer_after["trades_count"] == 1
        assert seller_after["trades_count"] == 1

        offer = await repos.offers.get_by_id(record["offer_id"])
        assert offer["status"] == "completed"

    async def test_deadline_survives_until_it_expires(self, bot, repos, trade):
        await _both_receive(bot, repos, trade)

        text, _ = await render_trades(repos, BUYER_TG)

        assert "Trade Protection" in text
        record = await repos.trades.get_by_id(trade)
        assert record["status"] == "holding"
        assert format_deadline(record["finalize_at"]) in text

    async def test_finalize_does_not_double_count(self, bot, repos, trade, duo):
        buyer, seller = duo

        await _both_receive(bot, repos, trade)
        await _expire_hold(repos, trade)
        await finalize_due(repos, await repos.trades.get_by_id(trade))
        await render_trades(repos, BUYER_TG)

        buyer_after = await repos.users.get_by_id(buyer["id"])
        seller_after = await repos.users.get_by_id(seller["id"])
        assert buyer_after["trades_count"] == 1
        assert seller_after["trades_count"] == 1

    async def test_cannot_complete_before_confirm(self, bot, repos, trade, session):
        await cb_trade_complete(make_callback(bot, f"trade_complete_{trade}", BUYER_TG), repos)

        record = await repos.trades.get_by_id(trade)
        assert record["status"] == "pending"
        assert any("не готова" in alert for alert in alerts(session))


class TestProtection:
    async def test_deadline_is_seven_days_after_last_receipt(self, bot, repos, trade):
        await _both_receive(bot, repos, trade)

        record = await repos.trades.get_by_id(trade)
        last_receipt = max(record["buyer_completed_at"], record["seller_completed_at"])
        held = _timestamp(record["finalize_at"]) - _timestamp(last_receipt)

        assert PROTECTION_DAYS == 7
        assert held.days == PROTECTION_DAYS
        assert held.seconds == 0

    async def test_rating_forbidden_in_holding(self, bot, repos, trade, session):
        await _both_receive(bot, repos, trade)

        await cb_rate_menu(make_callback(bot, f"rate_menu_{trade}", BUYER_TG), repos)
        await cb_rate(make_callback(bot, f"rate_{trade}_5", BUYER_TG), repos)

        seller = await repos.users.get_by_telegram_id(SELLER_TG)
        assert await repos.ratings.get_for_user(seller["id"]) == []
        assert any("Trade Protection" in alert for alert in alerts(session))

    async def test_rating_opens_after_hold_expires(self, bot, repos, trade, duo):
        buyer, seller = duo

        await _both_receive(bot, repos, trade)
        await _expire_hold(repos, trade)
        await cb_rate(make_callback(bot, f"rate_{trade}_5", BUYER_TG), repos)

        ratings = await repos.ratings.get_for_user(seller["id"])
        assert len(ratings) == 1
        assert ratings[0]["score"] == 5

    async def test_card_shows_cancel_in_steam_hint_and_button(self, bot, repos, trade, duo):
        await _both_receive(bot, repos, trade)

        text, markup = await render_trades(repos, BUYER_TG)
        buttons = [button.callback_data for row in markup.inline_keyboard for button in row]

        assert "может отменить трейд" in text
        assert f"trade_rollback_{trade}" in buttons
        assert f"trade_cancel_{trade}" not in buttons

    async def test_rollback_returns_trade_to_cancelled(self, bot, repos, trade, duo, session):
        buyer, seller = duo

        await _both_receive(bot, repos, trade)
        await cb_trade_rollback(make_callback(bot, f"trade_rollback_{trade}", SELLER_TG), repos)

        record = await repos.trades.get_by_id(trade)
        assert record["status"] == "cancelled"

        buyer_after = await repos.users.get_by_id(buyer["id"])
        seller_after = await repos.users.get_by_id(seller["id"])
        assert buyer_after["trades_count"] == 0
        assert seller_after["trades_count"] == 0

        offer = await repos.offers.get_by_id(record["offer_id"])
        assert offer["status"] == "active"
        assert any("Сделка отменена" in alert for alert in alerts(session))

    async def test_rollback_rejected_outside_holding(self, bot, repos, trade, session):
        await cb_trade_rollback(make_callback(bot, f"trade_rollback_{trade}", BUYER_TG), repos)

        record = await repos.trades.get_by_id(trade)
        assert record["status"] == "pending"
        assert any("Trade Protection" in alert for alert in alerts(session))

    def test_format_deadline_utc(self):
        assert format_deadline("2026-12-01 09:30:00") == "01.12.2026 09:30 UTC"
        assert format_deadline(None) == "—"


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

        await _both_receive(bot, repos, trade)
        await _expire_hold(repos, trade)

        await cb_rate(make_callback(bot, f"rate_{trade}_5", BUYER_TG), repos)

        ratings = await repos.ratings.get_for_user(seller["id"])
        assert len(ratings) == 1
        assert ratings[0]["score"] == 5

        seller_after = await repos.users.get_by_id(seller["id"])
        assert seller_after["rating"] == 5.0

    async def test_duplicate_rating_rejected(self, bot, repos, trade, duo, session):
        await _both_receive(bot, repos, trade)
        await _expire_hold(repos, trade)

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
        assert "предложение по обмену" in last_text(session)

        offer = await repos.offers.get_by_id(offer_id)
        assert offer["status"] == "in_trade"
