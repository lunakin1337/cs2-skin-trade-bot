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


def test_bottom_nav_has_primary_tabs_and_more_sheet():
    html = _html()

    assert 'class="tabbar"' in html
    assert 'id="tabs-more"' in html
    assert 'id="tabs-more-btn"' in html
    for tab in ["inventory", "catalog", "board", "trades", "profile"]:
        assert f'data-tab="{tab}"' in html
    assert "PRIMARY_TABS" in html


def test_mobile_layout_rules_present():
    html = _html()

    assert "@media (max-width: 480px)" in html
    assert "repeat(2, minmax(0, 1fr))" in html
    assert "env(safe-area-inset-bottom" in html


def test_catalog_filters_present():
    html = _html()

    for element in ['id="catalog-wear"', 'id="catalog-min"', 'id="catalog-max"', 'id="catalog-sort"', 'id="catalog-stattrak"']:
        assert element in html
    assert 'params.set("wear"' in html
    assert 'params.set("st", "1")' in html


def test_pickers_have_search_and_sort():
    html = _html()

    for element in ['id="counter-search"', 'id="counter-sort"', 'id="create-search"', 'id="create-sort"']:
        assert element in html
    assert 'state.counter.sort = state.counter.sort === "price_desc"' in html


def test_buttons_disabled_without_selection():
    html = _html()

    assert '$("counter-send").disabled = count === 0;' in html
    assert '$("create-publish").disabled = state.picked.size === 0;' in html


def test_back_button_and_haptics_are_wired():
    html = _html()

    assert "tg.BackButton.onClick(goBack)" in html
    assert "function syncBackButton()" in html
    assert "tabHistory: []" in html
    assert "tg.HapticFeedback.notificationOccurred" in html


def test_auto_refresh_and_badge_present():
    html = _html()

    assert 'id="badge-trades"' in html
    assert "AUTO_REFRESH_MS" in html
    assert "function refreshIncomingCount()" in html
    assert "setInterval(" in html


def test_thumbnails_use_small_steam_variant():
    html = _html()

    assert "function thumbUrl(url)" in html
    assert "/120fx120f" in html
    assert 'esc(thumbUrl(item.image))' in html


def test_counterparty_profile_screen_present():
    html = _html()

    assert 'id="view-user"' in html
    assert "async function loadUser(" in html
    assert "counterpart_id" in html
    assert 'switchTab("user")' in html


def test_auth_wall_for_browser_opening():
    html = _html()

    assert "function showAuthWall()" in html
    assert "auth-wall" in html
    assert "https://t.me/Cs2_p2pbot" in html
