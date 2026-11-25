"""Тесты API Mini App: авторизация через initData и данные пользователя."""

import json
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.services import inventory_sync
from bot.utils.steam import SteamInventory, SteamItem
from bot.utils.telegram_auth import build_init_data
from catalog_cache import bump_catalog_version
from config.settings import BotConfig
from web_app import create_app
from webapp_context import REPOS_KEY

TOKEN = "123456:AAHbbQ61o1k8P2uGpwVxpXLL5LDUe03x0Q"
TELEGRAM_ID = 555000111


def init_data(user_id: int = TELEGRAM_ID) -> str:
    return build_init_data(
        {
            "auth_date": str(int(time.time())),
            "query_id": "AAHtest",
            "user": json.dumps(
                {"id": user_id, "first_name": "Мария", "username": "masha"}
            ),
        },
        TOKEN,
    )


@pytest.fixture
async def client(tmp_path):
    app = create_app(
        config=BotConfig(token=TOKEN, web_admin_token="secret"),
        db_path=str(tmp_path / "webapp.db"),
    )
    async with TestClient(TestServer(app)) as instance:
        yield instance


def auth_headers(user_id: int = TELEGRAM_ID) -> dict[str, str]:
    return {"X-Telegram-Init-Data": init_data(user_id)}


class TestAuth:
    async def test_api_requires_init_data(self, client):
        response = await client.get("/api/me")
        assert response.status == 401

    async def test_bad_signature_rejected(self, client):
        response = await client.get(
            "/api/me",
            headers={"X-Telegram-Init-Data": init_data()[:-4] + "ffff"},
        )
        assert response.status == 401

    async def test_me_creates_user(self, client):
        response = await client.get("/api/me", headers=auth_headers())
        assert response.status == 200

        data = await response.json()
        assert data["telegram_id"] == TELEGRAM_ID
        assert data["username"] == "masha"
        assert data["steam"]["linked"] is False
        assert data["is_admin"] is False
        assert data["inventory"]["total"] == 0

    async def test_mini_app_page_served(self, client):
        response = await client.get("/")
        text = await response.text()

        assert response.status == 200
        assert "Telegram.WebApp" in text
        assert "/api/inventory" in text


class TestInventoryApi:
    async def test_inventory_pagination_and_prices(self, client):
        repos = client.app[REPOS_KEY]
        user = await repos.users.create_or_update(telegram_id=TELEGRAM_ID, username="masha")

        for index in range(3):
            await repos.items.add(
                owner_id=user["id"],
                steam_asset_id=f"10{index}",
                market_hash_name=f"AWP | Asiimov {index}",
                price_steam=100.0 + index,
                image_url="https://cdn.example/skin.png",
                rarity="Covert",
                exterior="Field-Tested",
            )

        response = await client.get("/api/inventory?page=0&size=2", headers=auth_headers())
        data = await response.json()

        assert response.status == 200
        assert data["total"] == 3
        assert data["pages"] == 2
        assert len(data["items"]) == 2
        assert data["items"][0]["image"] == "https://cdn.example/skin.png"
        assert data["items"][0]["price"] >= 100.0

    async def test_sync_without_steam_returns_error(self, client):
        response = await client.post("/api/inventory/sync", headers=auth_headers())
        data = await response.json()

        assert response.status == 400
        assert data["ok"] is False
        assert "SteamID" in data["error"]

    async def test_sync_saves_items(self, client, monkeypatch):
        repos = client.app[REPOS_KEY]
        user = await repos.users.create_or_update(telegram_id=TELEGRAM_ID, username="masha")
        await repos.users.link_steam(
            user["id"],
            "76561198000000000",
            "https://steamcommunity.com/tradeoffer/new/?partner=7&token=abc",
            trade_partner="7",
            trade_token="abc",
        )

        class FakeSteam:
            async def fetch_inventory(self, steam_id, language="russian"):
                return SteamInventory(
                    steam_id=steam_id,
                    items=[
                        SteamItem(
                            asset_id="777",
                            class_id="1",
                            instance_id="0",
                            market_hash_name="M4A1-S | Printstream",
                            image_url="https://cdn.example/m4.png",
                            tradable=True,
                        )
                    ],
                )

        monkeypatch.setattr(inventory_sync, "get_steam_client", lambda key="": FakeSteam())

        class FakePrices:
            async def fetch_prices(self, names, limit=20):
                return {}

        monkeypatch.setattr(inventory_sync, "get_price_fetcher", lambda: FakePrices())

        response = await client.post("/api/inventory/sync", headers=auth_headers())
        data = await response.json()

        assert response.status == 200
        assert data["ok"] is True
        assert data["created"] == 1

        items = await repos.items.get_by_owner(user["id"])
        assert items[0]["market_hash_name"] == "M4A1-S | Printstream"


class TestOffersApi:
    async def test_offers_list_marks_own(self, client):
        repos = client.app[REPOS_KEY]
        me = await repos.users.create_or_update(telegram_id=TELEGRAM_ID, username="masha")
        other = await repos.users.create_or_update(telegram_id=777000111, username="other")

        await repos.offers.create(
            creator_id=me["id"], title="Моё", items_offered=[], items_wanted="нож"
        )
        await repos.offers.create(
            creator_id=other["id"], title="Чужое", items_offered=[], items_wanted="кейсы"
        )

        response = await client.get("/api/offers", headers=auth_headers())
        data = await response.json()

        assert response.status == 200
        own = {offer["title"]: offer["own"] for offer in data["items"]}
        assert own == {"Моё": True, "Чужое": False}


class TestAdminPages:
    async def test_admin_requires_token(self, client):
        assert (await client.get("/stats")).status == 403

    async def test_admin_with_token(self, client):
        response = await client.get("/stats?token=secret")

        assert response.status == 200
        assert "Статистика" in await response.text()


class TestOffersBoard:
    async def _items(self, repos, telegram_id: int, count: int = 1) -> list[int]:
        user = await repos.users.get_by_telegram_id(telegram_id)
        created = []
        for index in range(count):
            created.append(
                await repos.items.add(
                    owner_id=user["id"],
                    steam_asset_id=f"{telegram_id}-{index}",
                    market_hash_name=f"AWP | Asiimov (Field-Tested) {index}",
                    price_steam=100.0 + index,
                )
            )
        return created

    async def test_create_and_delete_own_offer(self, client):
        repos = client.app[REPOS_KEY]
        await repos.users.create_or_update(telegram_id=TELEGRAM_ID, username="masha")
        await repos.skins.upsert_many([{"market_hash_name": "AK-47 | Redline (Field-Tested)"}])
        item_ids = await self._items(repos, TELEGRAM_ID)

        created = await client.post(
            "/api/offers",
            headers=auth_headers(),
            json={"item_ids": item_ids, "wanted": "ак редлайн"},
        )
        body = await created.json()
        assert created.status == 200
        assert body["wanted"] == "AK-47 | Redline (Field-Tested)"

        mine = await (await client.get("/api/my_offers", headers=auth_headers())).json()
        assert mine["items"][0]["id"] == body["id"]

        deleted = await client.post(f"/api/offers/{body['id']}/delete", headers=auth_headers())
        assert deleted.status == 200

        mine = await (await client.get("/api/my_offers", headers=auth_headers())).json()
        assert mine["items"] == []

    async def test_cannot_accept_own_offer(self, client):
        repos = client.app[REPOS_KEY]
        user = await repos.users.create_or_update(telegram_id=TELEGRAM_ID, username="masha")
        await repos.users.link_steam(
            user["id"],
            "76561198000000000",
            "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcd",
            trade_partner="1",
            trade_token="abcd",
        )
        item_ids = await self._items(repos, TELEGRAM_ID)
        offer_id = await repos.offers.create(
            creator_id=user["id"], title="Моё", items_offered=item_ids, items_wanted="—"
        )

        response = await client.post(f"/api/offers/{offer_id}/accept", headers=auth_headers())

        assert response.status == 400
        assert "своё" in (await response.json())["error"]

    async def test_board_hides_accept_for_own(self, client):
        repos = client.app[REPOS_KEY]
        user = await repos.users.create_or_update(telegram_id=TELEGRAM_ID, username="masha")
        other = await repos.users.create_or_update(telegram_id=999000111, username="other")
        await repos.offers.create(creator_id=user["id"], title="Моё", items_offered=[], items_wanted="a")
        await repos.offers.create(creator_id=other["id"], title="Чужое", items_offered=[], items_wanted="b")

        board = await (await client.get("/api/offers", headers=auth_headers())).json()
        own = {offer["title"]: offer["own"] for offer in board["items"]}
        assert own == {"Моё": True, "Чужое": False}


class TestTradesApi:
    async def test_full_trade_cycle(self, client):
        repos = client.app[REPOS_KEY]
        seller = await repos.users.create_or_update(telegram_id=999000111, username="seller")
        buyer = await repos.users.create_or_update(telegram_id=TELEGRAM_ID, username="masha")
        for participant in (seller, buyer):
            await repos.users.link_steam(
                participant["id"],
                "76561198000000000",
                "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcd",
                trade_partner="1",
                trade_token="abcd",
            )

        offer_id = await repos.offers.create(
            creator_id=seller["id"], title="Нож", items_offered=[], items_wanted="AWP"
        )

        accepted = await client.post(f"/api/offers/{offer_id}/accept", headers=auth_headers())
        trade_id = (await accepted.json())["trade_id"]

        for user_id in (TELEGRAM_ID, 999000111):
            response = await client.post(
                f"/api/trades/{trade_id}/confirm", headers=auth_headers(user_id)
            )
            assert response.status == 200

        trades = await (await client.get("/api/trades", headers=auth_headers())).json()
        assert trades["items"][0]["status"] == "in_escrow"
        assert trades["items"][0]["counterpart_url"].startswith("https://steamcommunity.com")

        for user_id in (TELEGRAM_ID, 999000111):
            await client.post(f"/api/trades/{trade_id}/complete", headers=auth_headers(user_id))

        trades = await (await client.get("/api/trades", headers=auth_headers())).json()
        hold = trades["items"][0]
        assert hold["status"] == "holding"
        assert hold["finalize_label"] and hold["finalize_at"]
        assert "Trade Protection" in hold["protection_note"]
        assert [action["name"] for action in hold["actions"]] == ["rollback"]
        assert hold["received"] is True

        early = await client.post(
            f"/api/trades/{trade_id}/rate", headers=auth_headers(), json={"score": 5}
        )
        assert early.status == 400

        await repos.db.execute(
            "UPDATE trades SET finalize_at = datetime('now', '-1 minute') WHERE id = ?", (trade_id,)
        )
        await repos.db.commit()

        trades = await (await client.get("/api/trades", headers=auth_headers())).json()
        assert trades["items"][0]["status"] == "completed"

        rated = await client.post(
            f"/api/trades/{trade_id}/rate", headers=auth_headers(), json={"score": 5}
        )
        assert rated.status == 200

        rating = await (await client.get("/api/rating", headers=auth_headers(999000111))).json()
        assert rating["average"] == 5.0

    async def test_rollback_after_steam_cancel(self, client):
        repos = client.app[REPOS_KEY]
        seller = await repos.users.create_or_update(telegram_id=999000222, username="seller2")
        buyer = await repos.users.create_or_update(telegram_id=TELEGRAM_ID, username="masha")
        for participant in (seller, buyer):
            await repos.users.link_steam(
                participant["id"],
                "76561198000000000",
                "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcd",
                trade_partner="1",
                trade_token="abcd",
            )

        offer_id = await repos.offers.create(
            creator_id=seller["id"], title="Перчатки", items_offered=[], items_wanted="AWP"
        )
        accepted = await client.post(f"/api/offers/{offer_id}/accept", headers=auth_headers())
        trade_id = (await accepted.json())["trade_id"]

        for user_id in (TELEGRAM_ID, 999000222):
            await client.post(f"/api/trades/{trade_id}/confirm", headers=auth_headers(user_id))
        for user_id in (TELEGRAM_ID, 999000222):
            await client.post(f"/api/trades/{trade_id}/complete", headers=auth_headers(user_id))

        rolled = await client.post(
            f"/api/trades/{trade_id}/rollback", headers=auth_headers()
        )
        assert rolled.status == 200
        assert (await rolled.json())["status"] == "cancelled"

        trade = await repos.trades.get_by_id(trade_id)
        assert trade["status"] == "cancelled"

        buyer_after = await repos.users.get_by_telegram_id(TELEGRAM_ID)
        assert buyer_after["trades_count"] == 0

        again = await client.post(
            f"/api/trades/{trade_id}/rollback", headers=auth_headers()
        )
        assert again.status == 400


class TestAdminApi:
    async def test_forbidden_for_regular_user(self, client):
        await client.get("/api/me", headers=auth_headers())
        response = await client.get("/api/admin/stats", headers=auth_headers())
        assert response.status == 403

    async def test_allowed_for_owner(self, client):
        response = await client.get("/api/admin/stats", headers=auth_headers(8851272459))
        assert response.status == 200
        assert "users" in await response.json()

    async def test_ban_user(self, client):
        repos = client.app[REPOS_KEY]
        target = await repos.users.create_or_update(telegram_id=TELEGRAM_ID, username="masha")

        response = await client.post(
            "/api/admin/ban",
            headers=auth_headers(8851272459),
            json={"telegram_id": TELEGRAM_ID},
        )
        assert response.status == 200

        banned = await repos.users.get_by_id(target["id"])
        assert banned["is_banned"] == 1


class TestCatalogApi:
    async def _seed(self, repos):
        await repos.skins.upsert_many(
            [
                {"market_hash_name": "AK-47 | Redline (Field-Tested)", "category": "rifles", "weapon": "AK-47"},
                {"market_hash_name": "AK-47 | Vulcan (Minimal Wear)", "category": "rifles", "weapon": "AK-47"},
                {"market_hash_name": "AWP | Asiimov (Field-Tested)", "category": "snipers", "weapon": "AWP"},
                {"market_hash_name": "★ Karambit | Doppler (Factory New)", "category": "knives", "weapon": None},
            ]
        )

    async def test_tree_groups_categories(self, client):
        await self._seed(client.app[REPOS_KEY])

        data = await (await client.get("/api/catalog/tree", headers=auth_headers())).json()
        by_code = {category["code"]: category for category in data["categories"]}

        assert by_code["rifles"]["count"] == 2
        assert by_code["knives"]["count"] == 1
        assert {weapon["weapon"] for weapon in by_code["rifles"]["weapons"]} == {"AK-47"}
        assert by_code["knives"]["weapons"] == []

    async def test_items_filter_by_category_and_weapon(self, client):
        await self._seed(client.app[REPOS_KEY])

        all_skins = await (await client.get("/api/catalog/items?category=rifles", headers=auth_headers())).json()
        assert all_skins["total"] == 2
        assert len(all_skins["items"]) == 2

        ak_only = await (
            await client.get("/api/catalog/items?category=rifles&weapon=AK-47", headers=auth_headers())
        ).json()
        assert ak_only["total"] == 2

        knives = await (await client.get("/api/catalog/items?category=knives", headers=auth_headers())).json()
        assert knives["items"][0]["name"].startswith("★ Karambit")

    async def test_pagination(self, client):
        repos = client.app[REPOS_KEY]
        await repos.skins.upsert_many(
            [
                {"market_hash_name": f"M4A4 | Skin {index}", "category": "rifles", "weapon": "M4A4"}
                for index in range(7)
            ]
        )

        first = await (await client.get("/api/catalog/items?category=rifles&size=3&page=0", headers=auth_headers())).json()
        second = await (await client.get("/api/catalog/items?category=rifles&size=3&page=1", headers=auth_headers())).json()

        assert first["pages"] == 3
        assert len(first["items"]) == 3
        assert {item["name"] for item in first["items"]}.isdisjoint({item["name"] for item in second["items"]})


class TestCatalogCache:
    async def _seed(self, repos, name="AK-47 | Redline (Field-Tested)"):
        await repos.skins.upsert_many([{"market_hash_name": name, "category": "rifles"}])

    async def test_response_carries_etag(self, client):
        await self._seed(client.app[REPOS_KEY])

        response = await client.get("/api/catalog/tree", headers=auth_headers())

        assert response.status == 200
        assert response.headers["ETag"].startswith('"')
        assert "max-age" in response.headers["Cache-Control"]

    async def test_if_none_match_returns_304(self, client):
        await self._seed(client.app[REPOS_KEY])
        first = await client.get("/api/catalog/tree", headers=auth_headers())
        etag = first.headers["ETag"]

        second = await client.get(
            "/api/catalog/tree",
            headers={**auth_headers(), "If-None-Match": etag},
        )

        assert second.status == 304
        assert await second.text() == ""

    async def test_cached_body_ignores_new_rows_until_version_bump(self, client):
        repos = client.app[REPOS_KEY]
        await self._seed(repos)

        first = await (await client.get("/api/catalog/tree", headers=auth_headers())).json()
        assert first["total"] == 1

        await self._seed(repos, name="AWP | Asiimov (Field-Tested)")
        cached = await (await client.get("/api/catalog/tree", headers=auth_headers())).json()
        assert cached["total"] == 1

        await bump_catalog_version(repos)
        fresh = await (await client.get("/api/catalog/tree", headers=auth_headers())).json()
        assert fresh["total"] == 2

    async def test_items_page_cached_per_filters(self, client):
        repos = client.app[REPOS_KEY]
        await self._seed(repos)

        rifles = await client.get("/api/catalog/items?category=rifles", headers=auth_headers())
        knives = await client.get("/api/catalog/items?category=knives", headers=auth_headers())

        assert rifles.headers["ETag"] != knives.headers["ETag"]
        assert (await knives.json())["total"] == 0

    async def test_zero_ttl_disables_cache(self, tmp_path):
        app = create_app(
            config=BotConfig(token=TOKEN, web_admin_token="secret", web_cache_ttl=0),
            db_path=str(tmp_path / "nocache.db"),
        )
        async with TestClient(TestServer(app)) as client:
            repos = client.app[REPOS_KEY]
            await self._seed(repos)
            await (await client.get("/api/catalog/tree", headers=auth_headers())).json()

            await self._seed(repos, name="AWP | Asiimov (Field-Tested)")
            fresh = await (await client.get("/api/catalog/tree", headers=auth_headers())).json()

            assert fresh["total"] == 2

    async def test_inventory_sync_invalidates_catalog_cache(self, client, monkeypatch):
        repos = client.app[REPOS_KEY]
        user = await repos.users.create_or_update(telegram_id=TELEGRAM_ID, username="masha")
        await repos.users.link_steam(
            user["id"],
            "76561198000000000",
            "https://steamcommunity.com/tradeoffer/new/?partner=7&token=abc",
            trade_partner="7",
            trade_token="abc",
        )
        before = await (await client.get("/api/catalog/tree", headers=auth_headers())).json()
        assert before["total"] == 0

        class FakeSteam:
            async def fetch_inventory(self, steam_id, language="russian"):
                return SteamInventory(
                    steam_id=steam_id,
                    items=[
                        SteamItem(
                            asset_id="900",
                            class_id="1",
                            instance_id="0",
                            market_hash_name="M4A1-S | Printstream",
                            tradable=True,
                        )
                    ],
                )

        class FakePrices:
            async def fetch_prices(self, names, limit=20):
                return {}

        monkeypatch.setattr(inventory_sync, "get_steam_client", lambda key="": FakeSteam())
        monkeypatch.setattr(inventory_sync, "get_price_fetcher", lambda: FakePrices())

        assert (await client.post("/api/inventory/sync", headers=auth_headers())).status == 200

        after = await (await client.get("/api/catalog/tree", headers=auth_headers())).json()
        assert after["total"] == 1

    async def test_catalog_items_include_rarity(self, client):
        repos = client.app[REPOS_KEY]
        user = await repos.users.create_or_update(telegram_id=TELEGRAM_ID, username="masha")
        await repos.items.add(
            owner_id=user["id"],
            steam_asset_id="555",
            market_hash_name="AWP | Asiimov (Field-Tested)",
            rarity="Засекреченное",
        )
        await self._seed(repos, name="AWP | Asiimov (Field-Tested)")

        data = await (await client.get("/api/catalog/items?q=Asiimov", headers=auth_headers())).json()

        assert data["items"][0]["rarity"] == "classified"  # канонический слаг, не русский тег


class TestCounterOffers:
    async def _prepare(self, client):
        repos = client.app[REPOS_KEY]
        seller = await repos.users.create_or_update(telegram_id=999000111, username="seller")
        buyer = await repos.users.create_or_update(telegram_id=TELEGRAM_ID, username="masha")
        for participant in (seller, buyer):
            await repos.users.link_steam(
                participant["id"],
                "76561198000000000",
                "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcd",
                trade_partner="1",
                trade_token="abcd",
            )

        seller_item = await repos.items.add(
            owner_id=seller["id"], steam_asset_id="asset-seller", market_hash_name="★ Karambit | Doppler",
            price_steam=1500.0,
        )
        buyer_item = await repos.items.add(
            owner_id=buyer["id"], steam_asset_id="asset-buyer", market_hash_name="AWP | Asiimov",
            price_steam=120.0,
        )
        offer_id = await repos.offers.create(
            creator_id=seller["id"], title="Нож", items_offered=[seller_item], items_wanted="AWP"
        )
        return seller, buyer, seller_item, buyer_item, offer_id

    async def test_counter_auto_confirms_initiator(self, client):
        seller, buyer, seller_item, buyer_item, offer_id = await self._prepare(client)

        response = await client.post(
            f"/api/offers/{offer_id}/accept",
            headers=auth_headers(),
            json={"item_ids": [buyer_item]},
        )
        data = await response.json()

        assert response.status == 200
        trade = await client.app[REPOS_KEY].trades.get_by_id(data["trade_id"])
        assert trade["buyer_confirmed_at"] is not None
        assert trade["seller_confirmed_at"] is None
        assert trade["status"] == "pending"

    async def test_trade_payload_has_items_and_steam_url(self, client):
        seller, buyer, seller_item, buyer_item, offer_id = await self._prepare(client)

        created = await client.post(
            f"/api/offers/{offer_id}/accept",
            headers=auth_headers(),
            json={"item_ids": [buyer_item]},
        )
        trade_id = (await created.json())["trade_id"]

        seller_view = await (await client.get("/api/trades", headers=auth_headers(999000111))).json()
        trade = seller_view["items"][0]

        assert trade["direction"] == "incoming"
        assert [item["name"] for item in trade["my_items"]] == ["★ Karambit | Doppler"]
        assert [item["name"] for item in trade["their_items"]] == ["AWP | Asiimov"]
        assert trade["steam_url"] is None, "ссылка не должна появляться до подтверждения обеих сторон"

        await client.post(f"/api/trades/{trade_id}/confirm", headers=auth_headers(999000111))

        seller_view = await (await client.get("/api/trades", headers=auth_headers(999000111))).json()
        ready = seller_view["items"][0]
        assert ready["status"] == "in_escrow"
        assert "items=" in ready["steam_url"]
        assert "asset-seller" in ready["steam_url"]

    async def test_counter_rejects_foreign_items(self, client):
        seller, buyer, seller_item, buyer_item, offer_id = await self._prepare(client)

        response = await client.post(
            f"/api/offers/{offer_id}/accept",
            headers=auth_headers(),
            json={"item_ids": [seller_item]},
        )
        assert response.status == 400
