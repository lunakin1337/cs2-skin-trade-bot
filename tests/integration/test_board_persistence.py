"""Объявление висит на доске, пока обмен не состоялся."""

import pytest

from bot.services.trades import settle_after_receipt


@pytest.fixture
async def parties(repos):
    seller = await repos.users.create_or_update(telegram_id=910001, username="seller")
    buyer = await repos.users.create_or_update(telegram_id=910002, username="buyer")
    item = await repos.items.add(
        owner_id=seller["id"], steam_asset_id="bp1", market_hash_name="AWP | Asiimov (Field-Tested)"
    )
    offer = await repos.offers.create(
        creator_id=seller["id"],
        title="AWP → AUG",
        items_offered=[item],
        items_wanted="AUG | Sweeper",
        wanted_name="AUG | Sweeper (Field-Tested)",
    )
    return {"seller": seller, "buyer": buyer, "offer": offer, "item": item}


async def test_offer_in_trade_stays_on_board(repos, parties):
    await repos.offers.update_status(parties["offer"], "in_trade")

    board = await repos.offers.get_active()
    names = [offer["id"] for offer in board]

    assert parties["offer"] in names
    assert await repos.offers.count_active() == 1


async def test_in_trade_offer_still_matches_inventory(repos, parties):
    await repos.offers.update_status(parties["offer"], "in_trade")

    matched = await repos.offers.active_for_names(["AUG | Sweeper (Field-Tested)"])

    assert [offer["id"] for offer in matched] == [parties["offer"]]


async def test_in_trade_offer_available_in_catalog(repos, parties):
    await repos.offers.update_status(parties["offer"], "in_trade")

    items = await repos.skins.available_items()

    assert [item["market_hash_name"] for item in items] == ["AWP | Asiimov (Field-Tested)"]


async def test_completed_and_cancelled_offers_leave_board(repos, parties):
    await repos.offers.update_status(parties["offer"], "in_trade")
    await repos.offers.update_status(parties["offer"], "completed")

    assert await repos.offers.count_active() == 0
    assert await repos.skins.available_items() == []


async def test_offer_completes_when_both_confirm_receipt(repos, parties):
    trade_id = await repos.trades.create(
        buyer_id=parties["buyer"]["id"], seller_id=parties["seller"]["id"], offer_id=parties["offer"]
    )
    await repos.offers.update_status(parties["offer"], "in_trade")
    await repos.trades.update_status(trade_id, "confirmed")
    await repos.trades.update_status(trade_id, "in_escrow")
    await repos.trades.set_completed_side(trade_id, "buyer")
    await repos.trades.set_completed_side(trade_id, "seller")

    trade = await repos.trades.get_by_id(trade_id)
    await settle_after_receipt(repos, trade)

    offer = await repos.offers.get_by_id(parties["offer"])
    assert offer["status"] == "completed"
    assert await repos.offers.count_active() == 0
