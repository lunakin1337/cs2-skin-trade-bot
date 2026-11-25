"""Интеграционные тесты фильтров каталога на уровне репозитория."""

import pytest

from database.repository import SkinRepository

CATALOG = [
    ("AWP | Asiimov (Field-Tested)", "snipers", "AWP", 45.0, "covert"),
    ("AWP | Asiimov (Factory New)", "snipers", "AWP", 180.0, "covert"),
    ("AK-47 | Redline (Field-Tested)", "rifles", "AK-47", 12.5, "classified"),
    ("StatTrak™ AK-47 | Redline (Field-Tested)", "rifles", "AK-47", 68.0, "classified"),
    ("P250 | Sand Dune (Battle-Scarred)", "pistols", "P250", 0.03, "consumer"),
]


@pytest.fixture
async def catalog(repos):
    await repos.skins.upsert_many(
        [
            {
                "market_hash_name": name,
                "category": category,
                "weapon": weapon,
                "price_value": price,
                "rarity": rarity,
            }
            for name, category, weapon, price, rarity in CATALOG
        ]
    )
    return repos.skins


async def test_sort_price_desc(catalog: SkinRepository):
    items = await catalog.list_items(sort="price_desc")

    assert [item["market_hash_name"] for item in items] == [
        "AWP | Asiimov (Factory New)",
        "StatTrak™ AK-47 | Redline (Field-Tested)",
        "AWP | Asiimov (Field-Tested)",
        "AK-47 | Redline (Field-Tested)",
        "P250 | Sand Dune (Battle-Scarred)",
    ]


async def test_filter_by_wear_code(catalog: SkinRepository):
    items = await catalog.list_items(wear="ft")

    assert len(items) == 3
    assert all("(Field-Tested)" in item["market_hash_name"] for item in items)


async def test_filter_by_price_range(catalog: SkinRepository):
    items = await catalog.list_items(min_price=10.0, max_price=70.0)

    names = [item["market_hash_name"] for item in items]
    assert names == [
        "AK-47 | Redline (Field-Tested)",
        "AWP | Asiimov (Field-Tested)",
        "StatTrak™ AK-47 | Redline (Field-Tested)",
    ]


async def test_filter_stattrak_and_count(catalog: SkinRepository):
    items = await catalog.list_items(stattrak=True)
    total = await catalog.count_items(stattrak=True)

    assert [item["market_hash_name"] for item in items] == ["StatTrak™ AK-47 | Redline (Field-Tested)"]
    assert total == 1


async def test_filters_combine(catalog: SkinRepository):
    items = await catalog.list_items(category="rifles", wear="ft", max_price=100.0, sort="price_desc")

    assert [item["market_hash_name"] for item in items] == [
        "StatTrak™ AK-47 | Redline (Field-Tested)",
        "AK-47 | Redline (Field-Tested)",
    ]


async def test_board_search_filters_offers(repos):
    author = await repos.users.create_or_update(telegram_id=999111, username="seller")
    other = await repos.users.create_or_update(telegram_id=999222, username="buyer")

    await repos.offers.create(
        creator_id=author["id"], title="AWP | Asiimov", items_offered=[1],
        items_wanted="AUG | Sweeper", wanted_name="AUG | Sweeper"
    )
    await repos.offers.create(
        creator_id=other["id"], title="Karambit | Doppler", items_offered=[2],
        items_wanted="AK-47 | Redline", wanted_name="AK-47 | Redline"
    )

    assert await repos.offers.count_active() == 2
    found = await repos.offers.get_active(query="sweeper")
    assert [offer["wanted_name"] for offer in found] == ["AUG | Sweeper"]
    assert await repos.offers.count_active(query="sweeper") == 1

    knives = await repos.offers.get_active(query="karambit redline")
    assert [offer["title"] for offer in knives] == ["Karambit | Doppler"]

    assert await repos.offers.get_active(query="нет такого") == []
