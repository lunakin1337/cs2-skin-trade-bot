"""Бан блокирует любые действия, а пропавшие предметы снимают объявление."""

import pytest

from bot.middlewares.ban import BANNED_TEXT, BanMiddleware


@pytest.fixture
async def banned(repos):
    user = await repos.users.create_or_update(telegram_id=770001, username="troll")
    await repos.users.ban(user["id"])
    return user


class FakeMessage:
    def __init__(self, user_id=770001):
        self.from_user = type("U", (), {"id": user_id})()
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)


class FakeCallback:
    def __init__(self, user_id=770001):
        self.from_user = type("U", (), {"id": user_id})()
        self.alerts = []

    async def answer(self, text=None, show_alert=False):
        self.alerts.append(text)


async def test_ban_middleware_stops_message(repos, banned):
    middleware = BanMiddleware(repos)
    event = FakeMessage()
    called = {"handler": False}

    async def handler(e, data):
        called["handler"] = True
        return "ok"

    result = await middleware(handler, event, {})

    assert result is None
    assert called["handler"] is False
    assert BANNED_TEXT in event.answers[0]


async def test_ban_middleware_stops_callback(repos, banned):
    middleware = BanMiddleware(repos)
    event = FakeCallback()
    called = {"handler": False}

    async def handler(e, data):
        called["handler"] = True

    await middleware(handler, event, {})

    assert called["handler"] is False
    assert event.alerts == [BANNED_TEXT]


async def test_unbanned_user_passes(repos):
    await repos.users.create_or_update(telegram_id=770002, username="ok")
    middleware = BanMiddleware(repos)
    called = {"handler": False}

    async def handler(e, data):
        called["handler"] = True
        return "ok"

    assert await middleware(handler, FakeMessage(770002), {}) == "ok"
    assert called["handler"] is True


async def test_unknown_user_passes(repos):
    middleware = BanMiddleware(repos)
    called = {"handler": False}

    async def handler(e, data):
        called["handler"] = True
        return "ok"

    assert await middleware(handler, FakeMessage(799999), {}) == "ok"
    assert called["handler"] is True


async def test_offer_cancelled_when_item_left_inventory(repos):
    owner = await repos.users.create_or_update(telegram_id=770003, username="holder")
    item = await repos.items.add(
        owner_id=owner["id"], steam_asset_id="x1", market_hash_name="AWP | Asiimov (Field-Tested)"
    )
    offer = await repos.offers.create(
        creator_id=owner["id"],
        title="AWP",
        items_offered=[item],
        items_wanted="AUG | Sweeper",
        wanted_name="AUG | Sweeper (Field-Tested)",
    )

    assert await repos.offers.cancel_with_missing_items(owner["id"]) == 0

    await repos.db.execute("DELETE FROM items WHERE id = ?", (item,))
    await repos.db.commit()

    assert await repos.offers.cancel_with_missing_items(owner["id"]) == 1
    assert (await repos.offers.get_by_id(offer))["status"] == "cancelled"
