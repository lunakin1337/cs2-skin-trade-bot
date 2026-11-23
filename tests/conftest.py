"""Pytest конфигурация и фикстуры."""

import pytest
import asyncio
import aiosqlite
import tempfile
import os
from pathlib import Path

from database import Database
from database.models import SCHEMA
from database.repository import Repositories


@pytest.fixture(scope="session")
def event_loop():
    """Создает event loop для всей сессии тестов."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db():
    """Создает временную БД для тестов."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db = Database(db_path=db_path)
    await db.connect()
    await db.init_schema(SCHEMA)

    yield db

    await db.close()
    os.unlink(db_path)


@pytest.fixture
async def repos(db):
    """Создает репозитории с тестовой БД."""
    return Repositories(db)


@pytest.fixture
async def test_user(repos):
    """Создает тестового пользователя."""
    user = await repos.users.create_or_update(
        telegram_id=123456789,
        username="testuser",
        first_name="Test",
        last_name="User",
    )
    return user


@pytest.fixture
async def test_user2(repos):
    """Создает второго тестового пользователя."""
    user = await repos.users.create_or_update(
        telegram_id=987654321,
        username="testuser2",
        first_name="Test2",
        last_name="User2",
    )
    return user