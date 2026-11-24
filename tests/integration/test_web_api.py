"""Тесты API Mini App: авторизация через initData и данные пользователя."""

import json
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.services import inventory_sync
from bot.utils.steam import SteamInventory, SteamItem
from bot.utils.telegram_auth import build_init_data
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
        assert trades["items"][0]["status"] == "completed"

        rated = await client.post(
            f"/api/trades/{trade_id}/rate", headers=auth_headers(), json={"score": 5}
        )
        assert rated.status == 200

        rating = await (await client.get("/api/rating", headers=auth_headers(999000111))).json()
        assert rating["average"] == 5.0


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
