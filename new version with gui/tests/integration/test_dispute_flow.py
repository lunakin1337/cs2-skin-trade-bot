"""Спор из бота: кнопка «⚠️ Открыть спор», причина текстом и уведомления."""

import pytest

from bot.handlers.trade_flow import cb_trade_dispute, msg_dispute_reason
from bot.states.trade import DisputeStates
from tests.helpers import alerts, make_callback, make_message

BUYER_TG = 123456789
SELLER_TG = 987654321
ADMIN_TG = 8851272459
REASON = "Продавец отправил обмен только на половину скинов"


@pytest.fixture
async def escrow_trade(repos):
    buyer = await repos.users.create_or_update(telegram_id=BUYER_TG, username="buyer")
    seller = await repos.users.create_or_update(telegram_id=SELLER_TG, username="seller")
    trade_id = await repos.trades.create(buyer_id=buyer["id"], seller_id=seller["id"])
    await repos.trades.update_status(trade_id, "in_escrow")
    return trade_id


def sent_calls(session, method: str) -> list:
    return [call for call in session.calls if type(call).__name__ == method]


class TestDisputeButton:
    async def test_callback_asks_for_reason(self, bot, repos, state, escrow_trade, session):
        await cb_trade_dispute(
            make_callback(bot, f"trade_dispute_{escrow_trade}", BUYER_TG), repos, state
        )

        assert await state.get_state() == DisputeStates.waiting_reason.state
        assert (await state.get_data())["dispute_trade_id"] == escrow_trade
        assert await repos.disputes.get_open_by_trade(escrow_trade) is None

    async def test_outsider_cannot_start(self, bot, repos, state, escrow_trade, session):
        await cb_trade_dispute(
            make_callback(bot, f"trade_dispute_{escrow_trade}", 555555555), repos, state
        )

        assert await state.get_state() is None
        assert any("не ваша сделка" in alert for alert in alerts(session))

    async def test_cancel_clears_state(self, bot, repos, state, escrow_trade, session):
        await cb_trade_dispute(
            make_callback(bot, f"trade_dispute_{escrow_trade}", BUYER_TG), repos, state
        )
        await cb_trade_dispute(make_callback(bot, "trade_dispute_cancel", BUYER_TG), repos, state)

        assert await state.get_state() is None
        assert await repos.disputes.get_open_by_trade(escrow_trade) is None


class TestDisputeReasonMessage:
    async def test_reason_message_opens_dispute_and_notifies(
        self, bot, repos, state, escrow_trade, config, session
    ):
        await cb_trade_dispute(
            make_callback(bot, f"trade_dispute_{escrow_trade}", BUYER_TG), repos, state
        )

        await msg_dispute_reason(
            make_message(bot, REASON, BUYER_TG, "buyer"), repos, state, config
        )

        dispute = await repos.disputes.get_open_by_trade(escrow_trade)
        assert dispute["reason"] == REASON
        assert await state.get_state() is None

        messages = {call.chat_id: call.text for call in sent_calls(session, "SendMessage")}
        assert ADMIN_TG in messages
        assert SELLER_TG in messages
        assert "Новый спор" in messages[ADMIN_TG]
        assert REASON in messages[SELLER_TG]

    async def test_second_dispute_is_refused(self, bot, repos, state, escrow_trade, config, session):
        buyer = await repos.users.get_by_telegram_id(BUYER_TG)
        await repos.disputes.create(escrow_trade, buyer["id"], "первый спор")

        await cb_trade_dispute(
            make_callback(bot, f"trade_dispute_{escrow_trade}", SELLER_TG), repos, state
        )

        assert await state.get_state() is None
        assert any("уже открыт спор" in alert for alert in alerts(session))

    async def test_short_reason_keeps_user_informed(
        self, bot, repos, state, escrow_trade, config, session
    ):
        await cb_trade_dispute(
            make_callback(bot, f"trade_dispute_{escrow_trade}", BUYER_TG), repos, state
        )
        await msg_dispute_reason(make_message(bot, "ой", BUYER_TG, "buyer"), repos, state, config)

        assert await repos.disputes.get_open_by_trade(escrow_trade) is None
        assert any("подробнее" in call.text for call in sent_calls(session, "SendMessage"))
