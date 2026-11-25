"""Конфигурация приложения."""

import os
from dataclasses import dataclass, field
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


def load_env_file(path: Path = ENV_PATH) -> None:
    """Загрузить .env в os.environ (переменные окружения имеют приоритет)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()


LLM_DEFAULT_BASE_URL = "https://api.openai.com/v1"
LLM_DEFAULT_MODEL = "gpt-4o-mini"
LLM_DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class LlmConfig:
    """Настройки ИИ-фолбэка разбора запроса «хочу» (ключ обязателен только для него)."""

    api_key: str = ""
    base_url: str = LLM_DEFAULT_BASE_URL
    model: str = LLM_DEFAULT_MODEL
    timeout: float = LLM_DEFAULT_TIMEOUT

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class BotConfig:
    token: str
    admin_ids: list[int] = field(default_factory=list)
    db_path: str = "data/bot.db"
    steam_api_key: str = ""
    web_app_url: str = ""
    web_admin_token: str = ""
    telegram_proxy: str = ""
    parse_mode: str = "HTML"
    web_cache_ttl: int = 60
    trade_reminder_minutes: int = 15
    super_admin_id: int = 0

    @property
    def has_steam_api_key(self) -> bool:
        return bool(self.steam_api_key)

    def is_admin(self, telegram_id: int | None) -> bool:
        return telegram_id is not None and telegram_id in self.admin_ids


def _int_env(name: str, default: int) -> int:
    """Целое из окружения: мусор и отрицательные значения дают дефолт."""
    try:
        value = int(os.getenv(name, "").strip())
    except ValueError:
        return default
    return value if value >= 0 else default


def load_config() -> BotConfig:
    """Собрать конфигурацию из переменных окружения."""
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("BOT_TOKEN не найден в переменных окружения")

    raw_admin_ids = os.getenv("ADMIN_IDS", "")
    admin_ids = [int(part) for part in raw_admin_ids.replace(" ", "").split(",") if part.strip()]

    return BotConfig(
        token=token,
        admin_ids=admin_ids,
        db_path=os.getenv("DB_PATH", "data/bot.db"),
        steam_api_key=os.getenv("STEAM_API_KEY", "").strip(),
        web_app_url=os.getenv("WEB_APP_URL", "").strip(),
        web_admin_token=os.getenv("WEB_ADMIN_TOKEN", "").strip(),
        telegram_proxy=os.getenv("TELEGRAM_PROXY", "").strip(),
        web_cache_ttl=_int_env("WEB_CACHE_TTL", 60),
        trade_reminder_minutes=_int_env("TRADE_REMINDER_MINUTES", 15),
        super_admin_id=_int_env("SUPER_ADMIN_ID", 0),
    )


def load_llm_config() -> LlmConfig:
    """Настройки LLM из окружения; без LLM_API_KEY фолбэк выключен."""
    raw_timeout = os.getenv("LLM_TIMEOUT", "").strip()
    try:
        timeout = float(raw_timeout) if raw_timeout else LLM_DEFAULT_TIMEOUT
    except ValueError:
        timeout = LLM_DEFAULT_TIMEOUT
    if timeout <= 0:
        timeout = LLM_DEFAULT_TIMEOUT

    return LlmConfig(
        api_key=os.getenv("LLM_API_KEY", "").strip(),
        base_url=os.getenv("LLM_BASE_URL", "").strip() or LLM_DEFAULT_BASE_URL,
        model=os.getenv("LLM_MODEL", "").strip() or LLM_DEFAULT_MODEL,
        timeout=timeout,
    )
