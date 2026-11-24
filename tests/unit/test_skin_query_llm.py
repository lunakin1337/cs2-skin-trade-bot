"""Тесты ИИ-фолбэка разбора «хочу» с мок-провайдером вместо HTTP."""

import asyncio
import json
import logging

import aiohttp

from bot.services.skin_query_llm import SkinQueryRefiner
from bot.services.skin_search import find_candidates
from config.settings import LlmConfig

QUERY = "что-то как у стримера, но подешевле"


class FakeResponse:
    """Ответ провайдера без сети."""

    def __init__(self, status: int = 200, body: str = ""):
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False


class FakeSession:
    """Мок HTTP-провайдера: записывает запросы, отдаёт заготовленные ответы/сбои."""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.closed = False

    def post(self, url, json=None, headers=None, timeout=None):
        self.requests.append({"url": url, "json": json, "headers": headers})
        response = self.responses.pop(0) if self.responses else FakeResponse(500, "")
        if isinstance(response, Exception):
            raise response
        return response


def llm_config(**overrides) -> LlmConfig:
    values = {
        "api_key": "test-key-should-not-leak",
        "base_url": "https://llm.test/v1",
        "model": "test-model",
        "timeout": 3.0,
    }
    values.update(overrides)
    return LlmConfig(**values)


def provider_reply(fields: dict, status: int = 200) -> FakeResponse:
    body = {"choices": [{"message": {"content": json.dumps(fields)}}]}
    return FakeResponse(status, json.dumps(body))


async def seed_asimov(repos, wear: str = "Field-Tested") -> None:
    await repos.skins.upsert_many(
        [
            {
                "market_hash_name": f"AWP | Asiimov ({wear})",
                "price_text": "$42.00",
                "price_value": 42.0,
            }
        ]
    )


async def test_local_match_never_calls_provider(repos):
    await seed_asimov(repos)
    session = FakeSession([])
    refiner = SkinQueryRefiner(llm_config(), session=session)

    found = await find_candidates(repos, "AWP Asiimov", refiner=refiner)

    assert [row["market_hash_name"] for row in found] == ["AWP | Asiimov (Field-Tested)"]
    assert session.requests == []


async def test_fallback_finds_when_local_result_empty(repos):
    await seed_asimov(repos)
    session = FakeSession(
        [
            provider_reply(
                {
                    "weapon": "AWP",
                    "market_hash_name": "AWP | Asiimov",
                    "exterior": "Field-Tested",
                    "max_price": 50,
                    "stattrak": False,
                }
            )
        ]
    )

    found = await find_candidates(repos, QUERY, refiner=SkinQueryRefiner(llm_config(), session=session))

    assert [row["market_hash_name"] for row in found] == ["AWP | Asiimov (Field-Tested)"]
    request = session.requests[0]
    assert request["url"] == "https://llm.test/v1/chat/completions"
    assert request["json"]["model"] == "test-model"
    assert request["json"]["messages"][-1]["content"] == QUERY


async def test_fallback_relaxes_wear_from_provider(repos):
    await seed_asimov(repos, wear="Minimal Wear")
    session = FakeSession(
        [
            provider_reply(
                {
                    "market_hash_name": "AWP | Asiimov (Field-Tested)",
                    "exterior": "Field-Tested",
                    "stattrak": False,
                }
            )
        ]
    )

    found = await find_candidates(repos, QUERY, refiner=SkinQueryRefiner(llm_config(), session=session))

    assert [row["market_hash_name"] for row in found] == ["AWP | Asiimov (Minimal Wear)"]


async def test_provider_timeout_returns_empty_without_exception(repos):
    await seed_asimov(repos)
    session = FakeSession([asyncio.TimeoutError(), asyncio.TimeoutError()])

    found = await find_candidates(repos, QUERY, refiner=SkinQueryRefiner(llm_config(), session=session))

    assert found == []
    assert len(session.requests) == 2


async def test_provider_server_error_retries_once_and_returns_empty(repos):
    await seed_asimov(repos)
    session = FakeSession([FakeResponse(503, ""), FakeResponse(503, "")])

    found = await find_candidates(repos, QUERY, refiner=SkinQueryRefiner(llm_config(), session=session))

    assert found == []
    assert len(session.requests) == 2


async def test_provider_client_error_is_not_retried(repos):
    await seed_asimov(repos)
    session = FakeSession([FakeResponse(401, "")])

    found = await find_candidates(repos, QUERY, refiner=SkinQueryRefiner(llm_config(), session=session))

    assert found == []
    assert len(session.requests) == 1


async def test_invalid_json_returns_empty(repos):
    await seed_asimov(repos)
    session = FakeSession([FakeResponse(200, "не json")])

    found = await find_candidates(repos, QUERY, refiner=SkinQueryRefiner(llm_config(), session=session))

    assert found == []


async def test_network_error_returns_empty(repos):
    await seed_asimov(repos)
    session = FakeSession([aiohttp.ClientError("нет сети"), aiohttp.ClientError("нет сети")])

    found = await find_candidates(repos, QUERY, refiner=SkinQueryRefiner(llm_config(), session=session))

    assert found == []


async def test_response_without_schema_fields_returns_empty(repos):
    await seed_asimov(repos)
    session = FakeSession([provider_reply({"weapon": None, "market_hash_name": None})])

    found = await find_candidates(repos, QUERY, refiner=SkinQueryRefiner(llm_config(), session=session))

    assert found == []


async def test_disabled_without_api_key_makes_no_request(repos):
    await seed_asimov(repos)
    session = FakeSession([provider_reply({"market_hash_name": "AWP | Asiimov"})])
    refiner = SkinQueryRefiner(llm_config(api_key=""), session=session)

    assert refiner.enabled is False
    assert await refiner.refine(QUERY) is None
    assert await find_candidates(repos, QUERY, refiner=refiner) == []
    assert session.requests == []


async def test_fallback_skipped_when_no_refiner_and_no_key(repos, monkeypatch):
    await seed_asimov(repos)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    assert await find_candidates(repos, QUERY) == []


async def test_logs_never_contain_key_or_query(repos, caplog):
    await seed_asimov(repos)
    session = FakeSession([asyncio.TimeoutError(), asyncio.TimeoutError()])

    with caplog.at_level(logging.WARNING):
        await find_candidates(repos, QUERY, refiner=SkinQueryRefiner(llm_config(), session=session))

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "test-key-should-not-leak" not in messages
    assert "стримера" not in messages
    assert "таймаут" in messages


async def test_wear_and_price_codes_are_normalized(repos):
    await repos.skins.upsert_many(
        [
            {
                "market_hash_name": "AK-47 | Redline (Minimal Wear)",
                "price_value": 30.0,
            },
            {
                "market_hash_name": "AK-47 | Redline (Field-Tested)",
                "price_value": 12.0,
            },
        ]
    )
    session = FakeSession(
        [
            provider_reply(
                {
                    "weapon": "AK-47",
                    "market_hash_name": "AK-47 | Redline",
                    "exterior": "mw",
                    "max_price": "25",
                    "stattrak": False,
                }
            )
        ]
    )

    found = await find_candidates(repos, QUERY, refiner=SkinQueryRefiner(llm_config(), session=session))

    assert [row["market_hash_name"] for row in found] == ["AK-47 | Redline (Minimal Wear)"]


def test_status_logged_once_and_without_key(caplog, monkeypatch):
    from bot.services import skin_query_llm

    monkeypatch.setattr(skin_query_llm, "_status_logged", False)
    with caplog.at_level(logging.INFO, logger="bot.services.skin_query_llm"):
        skin_query_llm.log_llm_status(llm_config(api_key=""))
        skin_query_llm.log_llm_status(llm_config())

    messages = [r.getMessage() for r in caplog.records if r.name == "bot.services.skin_query_llm"]
    assert len(messages) == 1
    assert "выключен" in messages[0]


def test_status_reports_model_when_key_present(caplog, monkeypatch):
    from bot.services import skin_query_llm

    monkeypatch.setattr(skin_query_llm, "_status_logged", False)
    with caplog.at_level(logging.INFO, logger="bot.services.skin_query_llm"):
        skin_query_llm.log_llm_status(llm_config())

    messages = [r.getMessage() for r in caplog.records if r.name == "bot.services.skin_query_llm"]
    assert len(messages) == 1
    assert "test-model" in messages[0]
    assert "test-key-should-not-leak" not in messages[0]
