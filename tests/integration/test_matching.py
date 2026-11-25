"""Подбор объявлений под инвентарь: репозиторий, API и бот-уведомления."""

import pytest

from database.repository import SkinRepository  # noqa: F401


@pytest.fixture
async def people(repos):
    holder = await repos.users.create_or_update(telegram_id=700001, username="holder")
    author = await repos.users.create_or_update(telegram_id=700002, username="author")
    other = await repos.users.create_or_update(telegram_id=700003, username="other")
    return {"holder": holder, "author": author, "other": other}


_COUNTER = {"n": 0}


async def _item(repos, owner, name, tradable=True):
    _COUNTER["n"] += 1
    return await repos.items.add(
        owner_id=owner["id"],
        steam_asset_id=f"asset-{owner['id']}-{_COUNTER['n']}",
        market_hash_name=name,
        is_tradable=1 if tradable else 0,
    )


async def test_owner_names_only_tradable(repos, people):
    holder = people["holder"]
    await _item(repos, holder, "AWP | Asiimov (Field-Tested)")
    await _item(repos, holder, "AWP | Asiimov (Field-Tested)")
    await _item(repos, holder, "Glock-18 | Fade (Factory New)", tradable=False)

    names = await repos.items.owner_names(holder["id"])

    assert names == ["AWP | Asiimov (Field-Tested)"]


async def test_active_for_names_matches_wanted_skin(repos, people):
    author = people["author"]
    holder = people["holder"]
    await _item(repos, holder, "AWP | Asiimov (Field-Tested)")
    await repos.offers.create(
        creator_id=author["id"],
        title="AK-47 | Redline → AWP | Asiimov",
        items_offered=[1],
        items_wanted="AWP | Asiimov (Field-Tested)",
        wanted_name="AWP | Asiimov (Field-Tested)",
    )
    await repos.offers.create(
        creator_id=author["id"],
        title="AK-47 | Redline → Glock | Fade",
        items_offered=[2],
        items_wanted="Glock-18 | Fade (Factory New)",
        wanted_name="Glock-18 | Fade (Factory New)",
    )

    names = await repos.items.owner_names(holder["id"])
    found = await repos.offers.active_for_names(names, exclude_user_id=holder["id"])

    assert [offer["wanted_name"] for offer in found] == ["AWP | Asiimov (Field-Tested)"]


async def test_active_for_names_skips_own_offers(repos, people):
    holder = people["holder"]
    await repos.offers.create(
        creator_id=holder["id"],
        title="своё",
        items_offered=[1],
        items_wanted="AWP | Asiimov (Field-Tested)",
        wanted_name="AWP | Asiimov (Field-Tested)",
    )

    assert await repos.offers.active_for_names(["AWP | Asiimov (Field-Tested)"], exclude_user_id=holder["id"]) == []


async def test_owners_wanting_finds_holders(repos, people):
    holder = people["holder"]
    await _item(repos, holder, "AWP | Asiimov (Field-Tested)")
    await _item(repos, people["other"], "AWP | Asiimov (Field-Tested)", tradable=False)

    owners = await repos.offers.owners_wanting("AWP | Asiimov (Field-Tested)", exclude_user_id=people["author"]["id"])

    assert [owner["telegram_id"] for owner in owners] == [700001]


async def test_owners_wanting_respects_exclusion(repos, people):
    holder = people["holder"]
    await _item(repos, holder, "AWP | Asiimov (Field-Tested)")

    owners = await repos.offers.owners_wanting("AWP | Asiimov (Field-Tested)", exclude_user_id=holder["id"])

    assert owners == []
