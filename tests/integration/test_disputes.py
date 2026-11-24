"""Споры из интерфейса: сервис открытия, уведомления и API Mini App."""

import json
import time

import pytest
from aiogram import Bot
from aiohttp.test_utils import TestClient, TestServer

from bot.services.disputes import DisputeError, notify_dispute, open_dispute
from bot.utils.telegram_auth import build_init_data
from config.settings import BotConfig
from tests.helpers import RecordingSession
from web_app import create_app
from webapp_context import BOT_KEY, REPOS_KEY

TOKEN = "123456:AAHbbQ61o1k8P2uGpwVxpXLL5LDUe03x0Q"
BUYER_TG = 555000111
SELLER_TG = 555000222
ADMIN_TG = 8851272459


def init_data(user_id: int) -> str:
    return build_init_data(
        {
            "auth_date": str(int(time.time())),
            "query_id": "AAHtest",
            "user": json.dumps({"id": user_id, "first_name": "Тест", "username": f"u{user_id}"}),
        },
        TOKEN,
    )


def auth_headers(user_id: int) -> dict[str, str]:
    return {"X-Telegram-Init-Data": init_data(user_id)}


@pytest.fixture
async def bot():
    instance = Bot(token=TOKEN, session=RecordingSession())
    yield instance
    await instance.session.close()


@pytest.fixture
async def client(bot, tmp_path):
    app = create_app(config=BotConfig(token=TOKEN), db_path=str(tmp_path / "disputes.db"))
    app[BOT_KEY] = bot
    async with TestClient(TestServer(app)) as instance:
        yield instance


@pytest.fixture
async def trade(client):
    """Сделка в in_escrow между двумя людьми."""
    repos = client.app[REPOS_KEY]
    seller = await repos.users.create_or_update(telegram_id=SELLER_TG, username="seller")
    buyer = await repos.users.create_or_update(telegram_id=BUYER_TG, username="buyer")
    trade_id = await repos.trades.create(buyer_id=buyer["id"], seller_id=seller["id"])
    await repos.trades.update_status(trade_id, "in_escrow")
    return {"id": trade_id, "buyer": buyer, "seller": seller}


def sent_texts(session: RecordingSession) -> list[tuple[int, str]]:
    return [
        (call.chat_id, call.text)
        for call in session.calls
        if type(call).__name__ == "SendMessage"
    ]


class TestOpenDisputeService:
    async def test_participant_opens_dispute(self, client, trade):
        repos = client.app[REPOS_KEY]

        dispute_id, record = await open_dispute(repos, trade["id"], trade["buyer"]["id"], "Продавец не отправил обмен")

        assert dispute_id > 0
        assert record["id"] == trade["id"]
        dispute = await repos.disputes.get_open_by_trade(trade["id"])
        assert dispute["reason"] == "Продавец не отправил обмен"
        assert dispute["opened_by"] == trade["buyer"]["id"]

    async def test_outsider_cannot_open(self, client, trade):
        repos = client.app[REPOS_KEY]
        stranger = await repos.users.create_or_update(telegram_id=555000333, username="stranger")

        with pytest.raises(DisputeError) as error:
            await open_dispute(repos, trade["id"], stranger["id"], "хочу пошуметь")

        assert error.value.status == 403

    async def test_short_reason_rejected(self, client, trade):
        repos = client.app[REPOS_KEY]

        with pytest.raises(DisputeError):
            await open_dispute(repos, trade["id"], trade["buyer"]["id"], "  ок  ")

        assert await repos.disputes.get_open_by_trade(trade["id"]) is None

    async def test_closed_trade_rejected(self, client, trade):
        repos = client.app[REPOS_KEY]
        await repos.trades.update_status(trade["id"], "cancelled")

        with pytest.raises(DisputeError):
            await open_dispute(repos, trade["id"], trade["buyer"]["id"], "уже отменили")

    async def test_second_dispute_rejected(self, client, trade):
        repos = client.app[REPOS_KEY]
        await open_dispute(repos, trade["id"], trade["buyer"]["id"], "первый спор")

        with pytest.raises(DisputeError) as error:
            await open_dispute(repos, trade["id"], trade["seller"]["id"], "второй спор")

        assert error.value.status == 409
        assert len(await repos.disputes.get_open()) == 1


class TestDisputeNotifications:
    async def test_admin_and_counterpart_notified(self, client, bot, trade):
        repos = client.app[REPOS_KEY]
        dispute_id, record = await open_dispute(repos, trade["id"], trade["buyer"]["id"], "не пришёл обмен")

        await notify_dispute(bot, repos, record, dispute_id, trade["buyer"]["id"], "не пришёл обмен")

        recipients = {chat_id: text for chat_id, text in sent_texts(bot.session)}
        assert ADMIN_TG in recipients
        assert SELLER_TG in recipients
        assert BUYER_TG not in recipients
        assert f"#{dispute_id}" in recipients[ADMIN_TG]
        assert "не пришёл обмен" in recipients[SELLER_TG]


class TestDisputeApi:
    async def test_open_dispute_from_mini_app(self, client, bot, trade):
        response = await client.post(
            f"/api/trades/{trade['id']}/dispute",
            headers=auth_headers(BUYER_TG),
            json={"reason": "Продавец перестал отвечать после обмена"},
        )

        assert response.status == 200
        body = await response.json()
        assert body["dispute_id"] > 0
        assert body["trade_id"] == trade["id"]

        recipients = {chat_id for chat_id, _ in sent_texts(bot.session)}
        assert {ADMIN_TG, SELLER_TG} <= recipients

    async def test_disputed_trade_hides_dispute_action(self, client, trade):
        await client.post(
            f"/api/trades/{trade['id']}/dispute",
            headers=auth_headers(SELLER_TG),
            json={"reason": "Покупатель не отправил свои скины"},
        )

        trades = await (await client.get("/api/trades", headers=auth_headers(SELLER_TG))).json()
        item = trades["items"][0]
        assert item["dispute_open"] is True
        assert "dispute" not in {action["name"] for action in item["actions"]}

    async def test_outsider_gets_403(self, client, trade):
        response = await client.post(
            f"/api/trades/{trade['id']}/dispute",
            headers=auth_headers(555000333),
            json={"reason": "чужой спор"},
        )

        assert response.status == 403

    async def test_empty_reason_gets_400(self, client, trade):
        response = await client.post(
            f"/api/trades/{trade['id']}/dispute",
            headers=auth_headers(BUYER_TG),
            json={"reason": ""},
        )

        assert response.status == 400

    async def test_duplicate_gets_409(self, client, trade):
        payload = {"reason": "обмен не состоялся"}
        first = await client.post(
            f"/api/trades/{trade['id']}/dispute", headers=auth_headers(BUYER_TG), json=payload
        )
        second = await client.post(
            f"/api/trades/{trade['id']}/dispute", headers=auth_headers(SELLER_TG), json=payload
        )

        assert first.status == 200
        assert second.status == 409

    async def test_requires_init_data(self, client, trade):
        response = await client.post(f"/api/trades/{trade['id']}/dispute", json={"reason": "без подписи"})

        assert response.status == 401
