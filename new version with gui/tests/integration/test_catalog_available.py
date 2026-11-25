"""Каталог «на обмене»: только скины из активных объявлений."""

import pytest


@pytest.fixture
async def board(repos):
    seller = await repos.users.create_or_update(telegram_id=880001, username="seller")
    keeper = await repos.users.create_or_update(telegram_id=880002, username="keeper")

    await repos.skins.upsert_many(
        [
            {"market_hash_name": "AWP | Asiimov (Field-Tested)", "category": "snipers", "weapon": "AWP", "price_value": 45.0},
            {"market_hash_name": "AK-47 | Redline (Field-Tested)", "category": "rifles", "weapon": "AK-47", "price_value": 12.5},
            {"market_hash_name": "Glock-18 | Fade (Factory New)", "category": "pistols", "weapon": "Glock-18", "price_value": 900.0},
        ]
    )

    awp = await repos.items.add(
        owner_id=seller["id"], steam_asset_id="a1", market_hash_name="AWP | Asiimov (Field-Tested)", price_steam=45.0
    )
    ak = await repos.items.add(
        owner_id=keeper["id"], steam_asset_id="a2", market_hash_name="AK-47 | Redline (Field-Tested)", price_steam=12.5
    )
    await repos.items.add(
        owner_id=keeper["id"], steam_asset_id="a3", market_hash_name="Glock-18 | Fade (Factory New)", price_steam=900.0
    )
    ak2 = await repos.items.add(
        owner_id=keeper["id"], steam_asset_id="a4", market_hash_name="AK-47 | Redline (Field-Tested)", price_steam=12.5
    )

    await repos.offers.create(
        creator_id=seller["id"], title="AWP", items_offered=[awp], items_wanted="AUG | Sweeper", wanted_name="AUG | Sweeper"
    )
    await repos.offers.create(
        creator_id=keeper["id"], title="AK", items_offered=[ak], items_wanted="AWP | Asiimov", wanted_name="AWP | Asiimov (Field-Tested)"
    )
    await repos.offers.create(
        creator_id=keeper["id"], title="AK", items_offered=[ak2], items_wanted="Karambit", wanted_name="Karambit | Doppler (Factory New)"
    )
    return repos


async def test_available_only_lists_offered_items(board):
    items = await board.skins.available_items()
    names = [item["market_hash_name"] for item in items]

    assert set(names) == {"AWP | Asiimov (Field-Tested)", "AK-47 | Redline (Field-Tested)"}
    assert "Glock-18 | Fade (Factory New)" not in names  # лежит в инвентаре, но не выставлен


async def test_available_counts_offers_per_skin(board):
    items = await board.skins.available_items()
    by_name = {item["market_hash_name"]: item for item in items}

    assert by_name["AK-47 | Redline (Field-Tested)"]["offers"] == 2
    assert by_name["AWP | Asiimov (Field-Tested)"]["offers"] == 1


async def test_available_filters_and_sort(board):
    assert await board.skins.count_available() == 2
    assert await board.skins.count_available(category="snipers") == 1
    assert await board.skins.count_available(query="Redline") == 1

    cheap_first = await board.skins.available_items(sort="price_asc")
    assert [item["market_hash_name"] for item in cheap_first] == [
        "AK-47 | Redline (Field-Tested)",
        "AWP | Asiimov (Field-Tested)",
    ]


async def test_available_tree_counts_categories(board):
    total, categories = await board.skins.available_tree()

    assert total == 2
    codes = {category["code"]: category["count"] for category in categories}
    assert codes == {"snipers": 1, "rifles": 1}


async def test_cancelled_offer_leaves_catalog(board, repos):
    seller = await repos.users.get_by_telegram_id(880001)
    offers = await repos.offers.get_by_creator(seller["id"])
    await repos.offers.update_status(offers[0]["id"], "cancelled")

    names = [item["market_hash_name"] for item in await board.skins.available_items()]
    assert names == ["AK-47 | Redline (Field-Tested)"]
