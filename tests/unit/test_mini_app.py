"""Проверки Mini App: разметка и синтаксис встроенного JS."""

import re
from pathlib import Path

import pytest

esprima = pytest.importorskip("esprima")

APP_HTML = Path(__file__).resolve().parents[2] / "src" / "webapp" / "app.html"


def _html() -> str:
    return APP_HTML.read_text(encoding="utf-8")


def test_page_has_all_tabs():
    html = _html()
    tabs = set(re.findall(r'data-tab="([a-z]+)"', html))

    assert {"inventory", "board", "create", "mine", "trades", "profile", "rating", "admin", "help"} <= tabs


def test_api_uses_init_data_header():
    html = _html()

    assert "X-Telegram-Init-Data" in html
    assert "telegram-web-app.js" in html


def test_inline_scripts_parse():
    scripts = re.findall(r"<script>(.*?)</script>", _html(), flags=re.S)
    assert scripts, "в Mini App нет встроенного скрипта"

    for index, code in enumerate(scripts):
        esprima.parseScript(code)  # бросит исключение на синтаксической ошибке
