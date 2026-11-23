"""Тесты проверки подписи initData Telegram Mini App."""

import json
import time

from bot.utils.telegram_auth import build_init_data, parse_init_data

BOT_TOKEN = "123456:AAHbbQ61o1k8P2uGpwVxpXLL5LDUe03x0Q"


def make_init_data(auth_date: int | None = None, user_id: int = 42) -> str:
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohaB",
        "user": json.dumps({"id": user_id, "first_name": "Test", "username": "tester"}),
    }
    return build_init_data(fields, BOT_TOKEN)


class TestInitData:
    def test_valid_signature(self):
        parsed = parse_init_data(make_init_data(user_id=42), BOT_TOKEN)

        assert parsed is not None
        assert parsed["user"]["id"] == 42
        assert parsed["query_id"] == "AAHdF6IQAAAAAN0XohaB"

    def test_wrong_token_rejected(self):
        assert parse_init_data(make_init_data(), "999:wrong") is None

    def test_tampered_payload_rejected(self):
        init_data = make_init_data(user_id=42)
        tampered = init_data.replace("42", "43", 1)
        assert parse_init_data(tampered, BOT_TOKEN) is None

    def test_expired_rejected(self):
        old = int(time.time()) - 3 * 24 * 3600
        assert parse_init_data(make_init_data(auth_date=old), BOT_TOKEN) is None

    def test_missing_hash_rejected(self):
        assert parse_init_data("auth_date=1&user=%7B%7D", BOT_TOKEN) is None

    def test_empty_input(self):
        assert parse_init_data("", BOT_TOKEN) is None
        assert parse_init_data(make_init_data(), "") is None
