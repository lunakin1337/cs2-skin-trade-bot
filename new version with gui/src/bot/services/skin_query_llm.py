"""ИИ-фолбэк разбора запроса «хочу» через OpenAI-совместимый API.

Подключается только тогда, когда локальный матчер ничего не нашёл: запрос уходит
в модель, ответ (weapon, market_hash_name, exterior, max_price, stattrak) строго
проверяется и превращается в SkinQuery, после чего поиск по каталогу повторяется
уже с этими полями. Любой сбой провайдера — таймаут, 5xx, невалидный JSON — просто
возвращает None, поиск остаётся прежним.

Безопасность: ключ берётся только из окружения (.env), ни ключ, ни текст запроса
не попадают ни в логи, ни в ответы.
"""

import asyncio
import json
import logging
import re
from typing import Any, Optional

import aiohttp

from bot.utils.skin_query import SkinQuery
from config.settings import LlmConfig, load_llm_config

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 300
MAX_NAME_LENGTH = 120
MAX_TOKENS = 6
MAX_ATTEMPTS = 2  # один запрос и максимум один ретрай
MAX_PRICE_VALUE = 100000.0

EXTERIORS = ("Factory New", "Minimal Wear", "Field-Tested", "Well-Worn", "Battle-Scarred")
EXTERIOR_CODES = {
    "fn": "Factory New",
    "mw": "Minimal Wear",
    "ft": "Field-Tested",
    "ww": "Well-Worn",
    "bs": "Battle-Scarred",
    "factory new": "Factory New",
    "minimal wear": "Minimal Wear",
    "field-tested": "Field-Tested",
    "well-worn": "Well-Worn",
    "battle-scarred": "Battle-Scarred",
}
WEAR_IN_NAME_RE = re.compile(r"\((?:%s)\)" % "|".join(EXTERIORS), re.I)
NAME_TOKEN_RE = re.compile(r"[0-9a-z][0-9a-z'\-]*", re.I)
SKIP_TOKENS = {"stattrak", "souvenir"}

SYSTEM_PROMPT = (
    "Ты разбираешь запрос игрока CS2 в поля каталога скинов Steam Community Market. "
    "Ответ — только JSON без пояснений, по схеме: "
    '{"weapon": string|null, "market_hash_name": string|null, "exterior": '
    '"Factory New"|"Minimal Wear"|"Field-Tested"|"Well-Worn"|"Battle-Scarred"|null, '
    '"max_price": number|null, "stattrak": boolean}. '
    "market_hash_name — точное название предмета из Steam, если уверен в нём. "
    "weapon — оружие или тип предмета (AWP, Karambit, Sticker). "
    "max_price — максимальная цена в долларах. Если поле не названо — null."
)


class _ProviderError(Exception):
    """Ответ провайдера, который бессмысленно повторять (4xx, невалидный JSON)."""


class _RetryableError(Exception):
    """Временный сбой: таймаут, сеть, 5xx — допустим один ретрай."""


class SkinQueryRefiner:
    """Разбор запроса моделью; None при выключенном ключе или любом сбое."""

    def __init__(self, config: LlmConfig, session: Optional[aiohttp.ClientSession] = None):
        self._config = config
        self._session = session

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    async def refine(self, text: str) -> Optional[SkinQuery]:
        text = (text or "").strip()[:MAX_TEXT_LENGTH]
        if not self.enabled or not text:
            return None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                body = await self._request(text)
            except _RetryableError as error:
                logger.warning(
                    "ИИ-разбор «хочу»: %s (попытка %s из %s)", error, attempt, MAX_ATTEMPTS
                )
                continue
            except _ProviderError as error:
                logger.warning("ИИ-разбор «хочу»: провайдер не дал результат (%s)", error)
                return None

            query = _query_from_response(text, body)
            if query is None:
                logger.warning("ИИ-разбор «хочу»: ответ не совпал со схемой, поиск локальный")
            return query
        return None

    async def _request(self, text: str) -> Any:
        timeout = aiohttp.ClientTimeout(total=self._config.timeout)
        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "temperature": 0,
            "max_tokens": 200,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        url = self._config.base_url.rstrip("/") + "/chat/completions"

        session = self._session
        owned = session is None or getattr(session, "closed", True)
        if owned:
            session = aiohttp.ClientSession(timeout=timeout)
        try:
            async with session.post(url, json=payload, headers=headers, timeout=timeout) as response:
                if response.status >= 500 or response.status == 429:
                    raise _RetryableError(f"HTTP {response.status}")
                if not response.ok:
                    raise _ProviderError(f"HTTP {response.status}")
                return json.loads(await response.text())
        except asyncio.TimeoutError as error:
            raise _RetryableError("таймаут") from error
        except aiohttp.ClientError as error:
            raise _RetryableError(type(error).__name__) from error
        except ValueError as error:
            raise _ProviderError("невалидный JSON") from error
        finally:
            if owned:
                await session.close()


def _query_from_response(raw_text: str, body: Any) -> Optional[SkinQuery]:
    data = _message_json(body)
    if data is None:
        return None
    return _query_from_fields(raw_text, data)


def _message_json(body: Any) -> Optional[dict]:
    """Достать JSON-объект из ответа /chat/completions."""
    if not isinstance(body, dict):
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        return None
    try:
        data = json.loads(content)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _query_from_fields(raw_text: str, data: dict) -> Optional[SkinQuery]:
    """Строгая проверка полей схемы; None, если из ответа нечего взять."""
    name = _clean_string(data.get("market_hash_name"), MAX_NAME_LENGTH)
    weapon = _clean_string(data.get("weapon"), MAX_NAME_LENGTH)
    tokens = _name_tokens(name) if name else []
    if not tokens and weapon:
        tokens = _name_tokens(weapon)

    wear = _exterior(data.get("exterior"))
    max_price = _price(data.get("max_price"))
    if not tokens and wear is None and max_price is None:
        return None

    return SkinQuery(
        raw=raw_text,
        tokens=tokens,
        wear=wear,
        max_price=max_price,
        stattrak=data.get("stattrak") is True,
    )


def _clean_string(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _exterior(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return EXTERIOR_CODES.get(value.strip().lower())


def _price(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        price = float(value)
    elif isinstance(value, str):
        try:
            price = float(value.replace(",", ".").strip())
        except ValueError:
            return None
    else:
        return None
    if price <= 0 or price > MAX_PRICE_VALUE:
        return None
    return price


def _name_tokens(name: str) -> list[str]:
    """«★ StatTrak™ AWP | Asiimov (Field-Tested)» → токены для поиска по LIKE."""
    text = WEAR_IN_NAME_RE.sub(" ", name)
    tokens: list[str] = []
    for token in NAME_TOKEN_RE.findall(text):
        token = token.lower()
        if token in SKIP_TOKENS or token in tokens:
            continue
        tokens.append(token)
    return tokens[:MAX_TOKENS]


_refiner: Optional[SkinQueryRefiner] = None
_refiner_config: Optional[LlmConfig] = None
_status_logged = False


def get_refiner() -> Optional[SkinQueryRefiner]:
    """Общий разборщик, пока ключ задан; None — фолбэк выключен."""
    global _refiner, _refiner_config
    config = load_llm_config()
    if not config.enabled:
        return None
    if _refiner is None or _refiner_config != config:
        _refiner = SkinQueryRefiner(config)
        _refiner_config = config
    return _refiner


def log_llm_status(config: Optional[LlmConfig] = None) -> None:
    """Один info при старте: включён ли фолбэк. Без ключа и текста запросов."""
    global _status_logged
    if _status_logged:
        return
    _status_logged = True

    settings = config if config is not None else load_llm_config()
    if settings.enabled:
        logger.info("ИИ-разбор «хочу» включён: модель %s", settings.model)
    else:
        logger.info("ИИ-разбор «хочу» выключен: LLM_API_KEY не задан")
