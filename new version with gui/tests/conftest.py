"""Pytest фикстуры: временная база с применёнными миграциями."""

import os
import tempfile

import pytest

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from config.settings import BotConfig
from database import Repositories, init_database
from tests.helpers import RecordingSession


@pytest.fixture
async def db():
    """Временная БД, схема поднимается миграциями — как в проде."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        db_path = handle.name

    database = await init_database(db_path)
    try:
        yield database
    finally:
        await database.close()
        os.unlink(db_path)


@pytest.fixture
async def repos(db):
    return Repositories(db)


@pytest.fixture
async def test_user(repos):
    return await repos.users.create_or_update(
        telegram_id=123456789,
        username="testuser",
        first_name="Test",
        last_name="User",
    )


@pytest.fixture
async def test_user2(repos):
    return await repos.users.create_or_update(
        telegram_id=987654321,
        username="testuser2",
        first_name="Test2",
        last_name="User2",
    )


@pytest.fixture
def config():
    return BotConfig(
        token="test_token",
        admin_ids=[8851272459],
        db_path="test.db",
        steam_api_key="",
    )


@pytest.fixture
def session():
    return RecordingSession()


@pytest.fixture
def bot(session):
    instance = Bot(token="1234567890:AAHbbQ61o1k8P2uGpwVxpXLL5LDUe03x0Q")
    instance.session = session
    return instance


@pytest.fixture
async def state():
    storage = MemoryStorage()
    context = FSMContext(storage=storage, key=(123456789, 123456789))
    yield context
    await storage.close()


@pytest.fixture(autouse=True)
def _reset_api_rate_limits():
    """Изолировать in-memory троттлинг API между тестами."""
    import web_app as web_app_module

    web_app_module._api_hit_timestamps.clear()
    yield
    web_app_module._api_hit_timestamps.clear()
