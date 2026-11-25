"""Проверка подписи Telegram WebApp (initData)."""

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Optional
from urllib.parse import parse_qsl

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_SECONDS = 24 * 3600


def parse_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> Optional[dict[str, Any]]:
    """Проверить initData из Mini App и вернуть разобранные поля.

    Подпись считается по алгоритму Telegram: HMAC-SHA256 с ключом
    ``HMAC_SHA256("WebAppData", bot_token)`` от отсортированной строки полей.
    Возвращает None, если подпись неверна, данных нет или они протухли.
    """
    if not init_data or not bot_token:
        return None

    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except ValueError:
        return None

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        return None

    if auth_date and time.time() - auth_date > max_age_seconds:
        logger.debug("initData просрочен: %s", auth_date)
        return None

    user = None
    if pairs.get("user"):
        try:
            user = json.loads(pairs["user"])
        except ValueError:
            return None

    return {
        "user": user,
        "auth_date": auth_date,
        "query_id": pairs.get("query_id"),
    }


def build_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Собрать подписанный initData (для тестов и локальной отладки)."""
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    from urllib.parse import urlencode

    return urlencode({**fields, "hash": signature})
