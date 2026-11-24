"""Тесты парсинга Steam: trade URL, картинки, инвентарь."""

import pytest

from bot.utils.steam import TradeUrl, build_image_url, parse_inventory, parse_trade_url

ICON_HASH = (
    "-9a81dlWLwJ2UUGcVs_nsVtzdOEdtWwKGZZLQHTxDZ7I56KU0Zwwo4NUX4oFJZEHLbXH5ApeO4YmlhxYQknC"
    "RvCo04DEVlxuKTlSp4r2Cw"
)

ASSETS = [
    {"assetid": "111", "classid": "3107", "instanceid": "0", "amount": "1"},
    {"assetid": "222", "classid": "9999", "instanceid": "0", "amount": "3"},
]

DESCRIPTIONS = [
    {
        "classid": "3107",
        "instanceid": "0",
        "market_hash_name": "AK-47 | Redline (Field-Tested)",
        "name": "AK-47 | Redline",
        "icon_url": ICON_HASH,
        "tradable": 1,
        "marketable": 1,
        "commodity": 0,
        "tags": [
            {"category": "Rarity", "localized_tag_name": "Classified"},
            {"category": "Exterior", "localized_tag_name": "Field-Tested"},
            {"category": "Type", "localized_tag_name": "Винтовка"},
        ],
    }
]


class TestTradeUrl:
    @pytest.mark.parametrize(
        "raw",
        [
            "https://steamcommunity.com/tradeoffer/new/?partner=123456&token=AbCdEf12",
            "https://www.steamcommunity.com/tradeoffer/new/?partner=123456&token=AbCdEf12",
            "steamcommunity.com/tradeoffer/new/?partner=123456&token=AbCdEf12",
            "  https://steamcommunity.com/tradeoffer/new/?token=AbCdEf12&partner=123456  ",
        ],
    )
    def test_valid(self, raw):
        parsed = parse_trade_url(raw)
        assert parsed == TradeUrl(partner="123456", token="AbCdEf12")

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "https://example.com/tradeoffer/new/?partner=123456&token=AbCdEf12",
            "https://steamcommunity.com/tradeoffer/new/?partner=abc&token=AbCdEf12",
            "https://steamcommunity.com/tradeoffer/new/?partner=123456",
            "https://steamcommunity.com/profiles/76561198000000000",
        ],
    )
    def test_invalid(self, raw):
        assert parse_trade_url(raw) is None

    def test_normalized_url_and_mask(self):
        parsed = TradeUrl(partner="123456", token="AbCdEf12")
        assert parsed.url == "https://steamcommunity.com/tradeoffer/new/?partner=123456&token=AbCdEf12"
        assert "AbCdEf12" not in parsed.masked
        assert "123456" in parsed.masked


class TestImages:
    def test_build_image_url(self):
        assert build_image_url(ICON_HASH) == (
            "https://community.cloudflare.steamstatic.com/economy/image/" + ICON_HASH + "/360fx360f"
        )

    def test_build_image_url_without_hash(self):
        assert build_image_url(None) is None
        assert build_image_url("") is None


class TestTradeHold:
    def test_hold_marker_disables_trading(self):
        description = dict(DESCRIPTIONS[0])
        description["owner_descriptions"] = [
            {"value": "Tradable After Nov 30, 2026 (10:00:00) GMT"}
        ]

        item = parse_inventory(ASSETS[:1], [description])[0]

        assert item.trade_hold is True
        assert item.tradable is False
        assert item.as_row()["is_tradable"] == 0

    def test_item_without_hold_stays_tradable(self):
        description = dict(DESCRIPTIONS[0])
        description["owner_descriptions"] = [{"value": "Этот предмет можно обменять"}]

        item = parse_inventory(ASSETS[:1], [description])[0]

        assert item.trade_hold is False
        assert item.as_row()["is_tradable"] == 1


class TestInventoryParsing:
    def test_maps_description_tags(self):
        items = parse_inventory(ASSETS[:1], DESCRIPTIONS)
        assert len(items) == 1

        item = items[0]
        assert item.asset_id == "111"
        assert item.class_id == "3107"
        assert item.market_hash_name == "AK-47 | Redline (Field-Tested)"
        assert item.rarity == "Classified"
        assert item.exterior == "Field-Tested"
        assert item.item_type == "Винтовка"
        assert item.image_url.endswith(f"{ICON_HASH}/360fx360f")
        assert item.tradable is True

    def test_unknown_description_falls_back(self):
        items = parse_inventory(ASSETS[1:], DESCRIPTIONS)
        row = items[0].as_row()
        assert row["steam_asset_id"] == "222"
        assert row["market_hash_name"] == "Unknown item"
        assert row["is_tradable"] == 0

    def test_amount_and_row_mapping(self):
        item = parse_inventory(ASSETS[1:], DESCRIPTIONS)[0]
        assert item.amount == 3

        row = item.as_row()
        assert row["class_id"] == "9999"
        assert row["image_url"] is None
