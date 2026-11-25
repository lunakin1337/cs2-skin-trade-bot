"""Публичный профиль участника: рейтинг, сделки, отзывы."""

import json
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.utils.telegram_auth import build_init_data
from config.settings import BotConfig
from web_app import create_app

TOKEN = "123456:AAHbbQ61o1k8P2uGpwVxpXLL5LDUe03x0Q"
VIEWER = 555000222


def init_data(user_id: int = VIEWER) -> str:
    return build_init_data(
        {
            "auth_date": str(int(time.time())),
            "query_id": "AAHprofile",
            "user": json.dumps({"id": user_id, "first_name": "Зритель", "username": "viewer"}),
        },
        TOKEN,
    )


@pytest.fixture
async def client(tmp_path):
    app = create_app(config=BotConfig(token=TOKEN), db_path=str(tmp_path / "profile.db"))
    async with TestClient(TestServer(app)) as instance:
        yield instance


async def test_profile_returns_rating_and_reviews(client):
    from webapp_context import REPOS_KEY

    repos = client.app[REPOS_KEY]
    trader = await repos.users.create_or_update(
        telegram_id=555000333, username="trader", first_name="Трейдер"
    )
    await repos.db.execute(
        "UPDATE users SET trades_count = 7, steam_persona = 'Player', created_at = '2026-01-05 10:00:00' WHERE id = ?",
        (trader["id"],),
    )
    await repos.db.commit()

    viewer = await repos.users.create_or_update(telegram_id=VIEWER, username="viewer", first_name="Зритель")
    trade = await repos.trades.create(buyer_id=viewer["id"], seller_id=trader["id"], offer_id=1)
    await repos.ratings.create(trade, viewer["id"], trader["id"], 5, "Быстро и честно")

    response = await client.get(
        f"/api/users/{trader['id']}", headers={"X-Telegram-Init-Data": init_data()}
    )

    assert response.status == 200
    data = await response.json()
    assert data["name"] in {"@trader", "Трейдер"}
    assert data["trades_count"] == 7
    assert data["steam_persona"] == "Player"
    assert data["member_since"] == "2026-01-05"
    assert data["reviews_total"] == 1
    assert data["reviews"][0]["score"] == 5
    assert data["reviews"][0]["comment"] == "Быстро и честно"


async def test_profile_requires_auth(client):
    response = await client.get("/api/users/1")

    assert response.status == 401


async def test_unknown_profile_is_404(client):
    response = await client.get("/api/users/999999", headers={"X-Telegram-Init-Data": init_data()})

    assert response.status == 404
