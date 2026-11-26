"""Проверки Mini App: разметка, статика и синтаксис JS."""

import re
from pathlib import Path

import pytest

esprima = pytest.importorskip("esprima")

WEBAPP = Path(__file__).resolve().parents[2] / "src" / "webapp"
APP_HTML = WEBAPP / "app.html"
APP_JS = WEBAPP / "app.js"
APP_CSS = WEBAPP / "app.css"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_page_has_all_tabs():
    html = _text(APP_HTML)
    tabs = set(re.findall(r'data-tab="([a-z]+)"', html))

    assert {"inventory", "catalog", "board", "trades", "profile"} <= tabs


def test_static_assets_are_linked():
    html = _text(APP_HTML)

    assert 'href="/static/app.css"' in html
    assert 'src="/static/app.js"' in html
    assert "telegram-web-app.js" in html


def test_api_uses_init_data_header():
    assert "X-Telegram-Init-Data" in _text(APP_JS)


def test_external_scripts_parse():
    esprima.parseScript(_text(APP_JS))


def test_mobile_layout_rules_present():
    css = _text(APP_CSS)

    assert "@media (max-width: 480px)" in css
    assert "safe-area-inset-bottom" in css


def test_catalog_filters_present():
    script = _text(APP_JS)

    assert "catalog" in script
    assert "/api/catalog" in script
