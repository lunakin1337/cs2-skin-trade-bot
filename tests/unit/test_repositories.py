"""Unit-тесты для репозиториев."""

import json
import sqlite3

import pytest


class TestUserRepository:
    """Тесты UserRepository."""

    @pytest.mark.asyncio
    async def test_create_user(self, repos):
        user = await repos.users.create_or_update(
            telegram_id=111111111,
            username="newuser",
            first_name="New",
            last_name="User",
        )
        assert user["telegram_id"] == 111111111
        assert user["username"] == "newuser"
        assert user["is_steam_linked"] == 0
        assert user["is_banned"] == 0
        assert user["rating"] == 0.0
        assert user["trades_count"] == 0

    @pytest.mark.asyncio
    async def test_get_by_telegram_id(self, repos, test_user):
        user = await repos.users.get_by_telegram_id(123456789)
        assert user is not None
        assert user["telegram_id"] == 123456789
        assert user["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_get_nonexistent_user(self, repos):
        user = await repos.users.get_by_telegram_id(999999999)
        assert user is None

    @pytest.mark.asyncio
    async def test_link_steam(self, repos, test_user):
        await repos.users.link_steam(
            test_user["id"],
            "76561198000000000",
            "https://steamcommunity.com/tradeoffer/new/?partner=123&token=abc",
        )
        user = await repos.users.get_by_id(test_user["id"])
        assert user["is_steam_linked"] == 1
        assert user["steam_id"] == "76561198000000000"
        assert "partner=123" in user["steam_trade_url"]

    @pytest.mark.asyncio
    async def test_ban_unban(self, repos, test_user):
        await repos.users.ban(test_user["id"])
        user = await repos.users.get_by_id(test_user["id"])
        assert user["is_banned"] == 1

        await repos.users.unban(test_user["id"])
        user = await repos.users.get_by_id(test_user["id"])
        assert user["is_banned"] == 0


class TestItemRepository:
    """Тесты ItemRepository."""

    @pytest.mark.asyncio
    async def test_add_item(self, repos, test_user):
        item_id = await repos.items.add(
            owner_id=test_user["id"],
            steam_asset_id="1234567890",
            market_hash_name="AK-47 | Redline (Field-Tested)",
            item_name="AK-47 | Redline",
            item_type="Rifle",
            rarity="Classified",
            quality="Field-Tested",
            exterior="Field-Tested",
            float_value=0.15,
            paint_seed=123,
            stickers=json.dumps([{"name": "Sticker | Katowice 2014"}]),
            image_url="https://example.com/image.png",
            price_steam=25.50,
            price_csfloat=24.00,
            price_buff=23.50,
            is_tradable=True,
        )
        assert item_id > 0

        item = await repos.items.get_by_id(item_id)
        assert item is not None
        assert item["market_hash_name"] == "AK-47 | Redline (Field-Tested)"
        assert item["float_value"] == 0.15
        assert item["is_tradable"] == 1

    @pytest.mark.asyncio
    async def test_get_by_owner(self, repos, test_user):
        # Добавляем несколько предметов
        await repos.items.add(
            owner_id=test_user["id"],
            steam_asset_id="111",
            market_hash_name="Item 1",
            is_tradable=True,
        )
        await repos.items.add(
            owner_id=test_user["id"],
            steam_asset_id="222",
            market_hash_name="Item 2",
            is_tradable=False,
        )
        await repos.items.add(
            owner_id=test_user["id"],
            steam_asset_id="333",
            market_hash_name="Item 3",
            is_tradable=True,
        )

        all_items = await repos.items.get_by_owner(test_user["id"])
        assert len(all_items) == 3

        tradable = await repos.items.get_by_owner(test_user["id"], tradable_only=True)
        assert len(tradable) == 2
        assert all(i["is_tradable"] == 1 for i in tradable)


class TestOfferRepository:
    """Тесты OfferRepository."""

    @pytest.mark.asyncio
    async def test_create_offer(self, repos, test_user):
        offer_id = await repos.offers.create(
            creator_id=test_user["id"],
            title="Test Offer",
            items_offered=[1, 2, 3],
            items_wanted="AWP | Dragon Lore",
            description="Test description",
            price=100.0,
        )
        assert offer_id > 0

        offer = await repos.offers.get_by_id(offer_id)
        assert offer is not None
        assert offer["title"] == "Test Offer"
        assert json.loads(offer["items_offered"]) == [1, 2, 3]
        assert offer["items_wanted"] == "AWP | Dragon Lore"
        assert offer["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_active_offers(self, repos, test_user):
        await repos.offers.create(
            creator_id=test_user["id"],
            title="Offer 1",
            items_offered=[1],
            items_wanted="Item A",
        )
        await repos.offers.create(
            creator_id=test_user["id"],
            title="Offer 2",
            items_offered=[2],
            items_wanted="Item B",
        )

        offers = await repos.offers.get_active(limit=10)
        assert len(offers) == 2
        # Order may vary, just check both exist
        titles = {o["title"] for o in offers}
        assert titles == {"Offer 1", "Offer 2"}

    @pytest.mark.asyncio
    async def test_update_status(self, repos, test_user):
        offer_id = await repos.offers.create(
            creator_id=test_user["id"],
            title="Test",
            items_offered=[1],
            items_wanted="Item",
        )
        await repos.offers.update_status(offer_id, "completed")
        offer = await repos.offers.get_by_id(offer_id)
        assert offer["status"] == "completed"


class TestTradeRepository:
    """Тесты TradeRepository."""

    @pytest.mark.asyncio
    async def test_create_trade(self, repos, test_user, test_user2):
        trade_id = await repos.trades.create(
            buyer_id=test_user["id"],
            seller_id=test_user2["id"],
            offer_id=None,
        )
        assert trade_id > 0

        trade = await repos.trades.get_by_id(trade_id)
        assert trade is not None
        assert trade["buyer_id"] == test_user["id"]
        assert trade["seller_id"] == test_user2["id"]
        assert trade["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_by_user(self, repos, test_user, test_user2):
        await repos.trades.create(buyer_id=test_user["id"], seller_id=test_user2["id"])
        await repos.trades.create(buyer_id=test_user2["id"], seller_id=test_user["id"])

        trades1 = await repos.trades.get_by_user(test_user["id"])
        assert len(trades1) == 2

        trades2 = await repos.trades.get_by_user(test_user2["id"])
        assert len(trades2) == 2

    @pytest.mark.asyncio
    async def test_update_status(self, repos, test_user, test_user2):
        trade_id = await repos.trades.create(
            buyer_id=test_user["id"],
            seller_id=test_user2["id"],
        )
        await repos.trades.update_status(trade_id, "confirmed")
        trade = await repos.trades.get_by_id(trade_id)
        assert trade["status"] == "confirmed"


class TestTradeItemRepository:
    """Тесты TradeItemRepository."""

    @pytest.mark.asyncio
    async def test_add_trade_item(self, repos, test_user, test_user2):
        trade_id = await repos.trades.create(
            buyer_id=test_user["id"],
            seller_id=test_user2["id"],
        )
        item_id = await repos.items.add(
            owner_id=test_user2["id"],
            steam_asset_id="999",
            market_hash_name="Test Skin",
            is_tradable=True,
        )

        ti_id = await repos.trade_items.add(
            trade_id=trade_id,
            item_id=item_id,
            from_user_id=test_user2["id"],
            to_user_id=test_user["id"],
        )
        assert ti_id > 0

        items = await repos.trade_items.get_by_trade(trade_id)
        assert len(items) == 1
        assert items[0]["item_id"] == item_id


class TestRatingRepository:
    """Тесты RatingRepository."""

    @pytest.mark.asyncio
    async def test_create_rating(self, repos, test_user, test_user2):
        trade_id = await repos.trades.create(
            buyer_id=test_user["id"],
            seller_id=test_user2["id"],
        )
        rating_id = await repos.ratings.create(
            trade_id=trade_id,
            from_user_id=test_user["id"],
            to_user_id=test_user2["id"],
            score=5,
            comment="Great trade!",
        )
        assert rating_id > 0

        ratings = await repos.ratings.get_for_user(test_user2["id"])
        assert len(ratings) == 1
        assert ratings[0]["score"] == 5
        assert ratings[0]["comment"] == "Great trade!"

    @pytest.mark.asyncio
    async def test_average_rating(self, repos, test_user, test_user2):
        trade_id = await repos.trades.create(
            buyer_id=test_user["id"],
            seller_id=test_user2["id"],
        )
        await repos.ratings.create(
            trade_id=trade_id,
            from_user_id=test_user["id"],
            to_user_id=test_user2["id"],
            score=5,
        )

        avg = await repos.ratings.get_average_rating(test_user2["id"])
        assert avg == 5.0


class TestDisputeRepository:
    """Тесты DisputeRepository."""

    @pytest.mark.asyncio
    async def test_create_dispute(self, repos, test_user, test_user2):
        trade_id = await repos.trades.create(
            buyer_id=test_user["id"],
            seller_id=test_user2["id"],
        )
        dispute_id = await repos.disputes.create(
            trade_id=trade_id,
            opened_by=test_user["id"],
            reason="Seller didn't send items",
        )
        assert dispute_id > 0

        disputes = await repos.disputes.get_open()
        assert len(disputes) == 1
        assert disputes[0]["reason"] == "Seller didn't send items"

    @pytest.mark.asyncio
    async def test_only_one_open_dispute_per_trade(self, repos, test_user, test_user2):
        trade_id = await repos.trades.create(buyer_id=test_user["id"], seller_id=test_user2["id"])
        first = await repos.disputes.create(trade_id=trade_id, opened_by=test_user["id"], reason="раз")

        open_dispute = await repos.disputes.get_open_by_trade(trade_id)
        assert open_dispute["id"] == first

        with pytest.raises(sqlite3.IntegrityError):
            await repos.disputes.create(trade_id=trade_id, opened_by=test_user2["id"], reason="два")

        await repos.disputes.resolve(first, "решение")
        assert await repos.disputes.get_open_by_trade(trade_id) is None

        second = await repos.disputes.create(trade_id=trade_id, opened_by=test_user2["id"], reason="три")
        assert second != first

    @pytest.mark.asyncio
    async def test_resolve_dispute(self, repos, test_user, test_user2):
        trade_id = await repos.trades.create(
            buyer_id=test_user["id"],
            seller_id=test_user2["id"],
        )
        dispute_id = await repos.disputes.create(
            trade_id=trade_id,
            opened_by=test_user["id"],
            reason="Test reason",
        )
        await repos.disputes.resolve(dispute_id, "Resolved by admin")

        disputes = await repos.disputes.get_open()
        assert len(disputes) == 0


class TestSettingsRepository:
    """Тесты SettingsRepository."""

    @pytest.mark.asyncio
    async def test_get_set(self, repos):
        # Несуществующий ключ
        value = await repos.settings.get("nonexistent")
        assert value is None

        # Установка и получение
        await repos.settings.set("test_key", "test_value")
        value = await repos.settings.get("test_key")
        assert value == "test_value"

        # Обновление
        await repos.settings.set("test_key", "new_value")
        value = await repos.settings.get("test_key")
        assert value == "new_value"