"""Атомарность многошаговых операций со сделками (settle / revert / finalize)."""

import pytest

from bot.services.trades import (
    finalize_due,
    revert_after_trade_cancel,
    settle_after_receipt,
)

BUYER_TG = 123456789
SELLER_TG = 987654321


@pytest.fixture
async def duo(repos):
    seller = await repos.users.create_or_update(
        telegram_id=SELLER_TG, username="seller", first_name="Seller"
    )
    buyer = await repos.users.create_or_update(
        telegram_id=BUYER_TG, username="buyer", first_name="Buyer"
    )
    trade_url = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcd"
    for participant in (seller, buyer):
        await repos.users.link_steam(
            participant["id"], "76561198000000000", trade_url, trade_partner="1", trade_token="abcd"
        )
    return buyer, seller


@pytest.fixture
async def escrow_trade(repos, duo):
    """Сделка в in_escrow с обеими отметками получения — как перед settle."""
    buyer, seller = duo
    offer_id = await repos.offers.create(
        creator_id=seller["id"], title="Тест", items_offered=[], items_wanted="хочу"
    )
    trade_id = await repos.trades.create(buyer_id=buyer["id"], seller_id=seller["id"], offer_id=offer_id)
    now = "2026-01-01 12:00:00"
    await repos.db.execute(
        """
        UPDATE trades SET status = 'in_escrow',
            buyer_completed_at = ?, seller_completed_at = ?
        WHERE id = ?
        """,
        (now, now, trade_id),
    )
    await repos.db.commit()
    return trade_id, offer_id


class ExplodingRepo:
    """Прокси: подменяет один метод выбранного под-репозитория падением."""

    def __init__(self, real, sub: str, fail_method: str):
        for name in ("trades", "offers", "users", "items", "trade_items", "disputes", "ratings"):
            repo = getattr(real, name)
            if name == sub:
                repo = _BrokenMethodRepo(repo, fail_method)
            setattr(self, name, repo)
        self.db = real.db

    def __getattr__(self, name):
        return getattr(self._real, name)


class _BrokenMethodRepo:
    def __init__(self, real, fail_method: str):
        self._real = real
        self._fail = fail_method

    def __getattr__(self, name):
        if name == self._fail:
            raise RuntimeError("boom: имитация падения процесса")
        return getattr(self._real, name)


def _wrap(repos, sub: str, fail_method: str):
    return ExplodingRepo(repos, sub, fail_method)


class TestAtomicity:
    async def test_settle_failure_leaves_no_holding(self, repos, escrow_trade):
        """Падение после set_holding откатывает и сделку, и статус оффера."""
        trade_id, offer_id = escrow_trade
        broken = _wrap(repos, "offers", "update_status")

        with pytest.raises(RuntimeError, match="boom"):
            await settle_after_receipt(broken, dict(await repos.trades.get_by_id(trade_id)))

        record = await repos.trades.get_by_id(trade_id)
        assert record["status"] == "in_escrow"
        offer = await repos.offers.get_by_id(offer_id)
        assert offer["status"] != "completed"

    async def test_revert_failure_keeps_holding(self, repos, escrow_trade):
        """Падение при revert не должно оставлять сделку в промежуточном состоянии."""
        trade_id, offer_id = escrow_trade
        await settle_after_receipt(repos, dict(await repos.trades.get_by_id(trade_id)))
        assert (await repos.trades.get_by_id(trade_id))["status"] == "holding"

        broken = _wrap(repos, "offers", "update_status")
        with pytest.raises(RuntimeError, match="boom"):
            await revert_after_trade_cancel(broken, dict(await repos.trades.get_by_id(trade_id)))

        record = await repos.trades.get_by_id(trade_id)
        assert record["status"] == "holding"

    async def test_finalize_failure_keeps_counters(self, repos, escrow_trade):
        """Падение после finalize не должно оставлять счётчики без статуса completed."""
        trade_id, _ = escrow_trade
        await settle_after_receipt(repos, dict(await repos.trades.get_by_id(trade_id)))
        await repos.db.execute(
            "UPDATE trades SET finalize_at = datetime('now', '-1 minute') WHERE id = ?",
            (trade_id,),
        )
        await repos.db.commit()

        broken = _wrap(repos, "users", "increment_trades_count")
        with pytest.raises(RuntimeError, match="boom"):
            await finalize_due(broken, dict(await repos.trades.get_by_id(trade_id)))

        record = await repos.trades.get_by_id(trade_id)
        buyer_trades = (await repos.users.get_by_telegram_id(BUYER_TG))["trades_count"]
        assert record["status"] == "holding", "finalize должен откатиться вместе со счётчиками"
        assert buyer_trades == 0
