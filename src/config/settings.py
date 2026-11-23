"""Конфигурация бота."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BotConfig:
    token: str
    admin_ids: list[int]
    db_path: str = "data/bot.db"
    parse_mode: str = "HTML"
    steam_api_key: str = ""


def _load_env_file() -> None:
    """Загружает переменные из .env файла, если он существует."""
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


def load_config() -> BotConfig:
    """Загружает конфигурацию из переменных окружения."""
    _load_env_file()

    token = os.getenv("BOT_TOKEN", "")
    if not token:
        raise ValueError("BOT_TOKEN не найден в переменных окружения")

    admin_ids_raw = os.getenv("ADMIN_IDS", "")
    admin_ids = [int(x.strip()) for x in admin_ids_raw.split(",") if x.strip()] if admin_ids_raw else []

    db_path = os.getenv("DB_PATH", "data/bot.db")
    steam_api_key = os.getenv("STEAM_API_KEY", "")

    return BotConfig(
        token=token,
        admin_ids=admin_ids,
        db_path=db_path,
        steam_api_key=steam_api_key,
    )