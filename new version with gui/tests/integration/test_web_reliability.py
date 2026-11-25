"""Надёжность веб-слоя: ошибки API, идентификатор запроса, /health."""

import logging

import pytest
from aiohttp.test_utils import TestClient, TestServer

from config.settings import BotConfig
from web_app import create_app

TOKEN = "123456:AAHbbQ61o1k8P2uGpwVxpXLL5LDUe03x0Q"


def make_app(tmp_path):
    return create_app(config=BotConfig(token=TOKEN), db_path=str(tmp_path / "reliability.db"))


@pytest.fixture
async def client(tmp_path):
    app = make_app(tmp_path)
    async with TestClient(TestServer(app)) as instance:
        yield instance


@pytest.fixture
async def broken_client(tmp_path):
    """Приложение, где один маршрут падает намеренно."""
    app = make_app(tmp_path)

    async def boom(request):
        raise RuntimeError("нарочно сломано")

    app.router.add_get("/api/v1/broken", boom)
    async with TestClient(TestServer(app)) as instance:
        yield instance


async def test_unhandled_error_returns_json_with_request_id(broken_client, caplog):
    with caplog.at_level(logging.ERROR):
        response = await broken_client.get("/api/v1/broken")

    assert response.status == 500
    assert response.content_type == "application/json"
    payload = await response.json()
    assert payload["error"] == "internal"
    assert payload["request_id"]
    assert response.headers["X-Request-Id"] == payload["request_id"]
    assert any("необработанная ошибка" in record.message for record in caplog.records)


async def test_request_id_from_header_is_reused(broken_client):
    response = await broken_client.get("/api/v1/broken", headers={"X-Request-Id": "abc123"})

    assert (await response.json())["request_id"] == "abc123"


async def test_health_reports_database_state(client):
    response = await client.get("/health")

    assert response.status == 200
    payload = await response.json()
    assert payload["status"] == "ok"
    assert payload["db"] == "ok"
    assert payload["migrations"] >= 1


async def test_unauthorized_api_stays_json(client):
    response = await client.get("/api/me")

    assert response.status == 401
    assert (await response.json())["error"] == "unauthorized"


async def test_timing_is_logged_without_init_data(client, caplog):
    with caplog.at_level(logging.INFO):
        await client.get("/health")

    assert any("/health" in record.message for record in caplog.records)
    assert all("initData" not in record.message for record in caplog.records)
