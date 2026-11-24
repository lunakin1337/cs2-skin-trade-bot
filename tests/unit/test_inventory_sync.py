"""Тесты синхронизации инвентаря с базой."""


def row(asset_id: str, name: str, price_steam: float | None = None, tradable: bool = True) -> dict:
    return {
        "steam_asset_id": asset_id,
        "market_hash_name": name,
        "is_tradable": tradable,
        "is_marketable": True,
        "price_steam": price_steam,
    }


class TestInventorySync:
    async def test_initial_sync_inserts(self, repos, test_user):
        created, updated, removed = await repos.items.sync(
            test_user["id"],
            [row("111", "AK-47 | Redline (Field-Tested)"), row("222", "AWP | Asiimov")],
        )

        assert (created, updated, removed) == (2, 0, 0)
        assert await repos.items.count_by_owner(test_user["id"]) == 2

    async def test_resync_updates_and_prunes(self, repos, test_user):
        await repos.items.sync(test_user["id"], [row("111", "AK-47 | Redline"), row("222", "AWP")])

        created, updated, removed = await repos.items.sync(
            test_user["id"],
            [row("111", "AK-47 | Redline (Field-Tested)"), row("333", "M4A1-S | Printstream")],
        )

        assert (created, updated, removed) == (1, 1, 1)

        items = await repos.items.get_by_owner(test_user["id"])
        names = {item["market_hash_name"] for item in items}
        assert names == {"AK-47 | Redline (Field-Tested)", "M4A1-S | Printstream"}

    async def test_prices_are_applied(self, repos, test_user):
        await repos.items.sync(
            test_user["id"],
            [row("111", "AK-47 | Redline"), row("222", "AK-47 | Redline")],
        )

        await repos.items.apply_prices(test_user["id"], {"AK-47 | Redline": 42.5})

        assert await repos.items.sum_price(test_user["id"]) == 85.0
        items = await repos.items.get_by_owner(test_user["id"])
        assert all(item["price_steam"] == 42.5 for item in items)

    async def test_tradable_filter(self, repos, test_user):
        await repos.items.sync(
            test_user["id"],
            [row("111", "Tradable", tradable=True), row("222", "Locked", tradable=False)],
        )

        assert await repos.items.count_by_owner(test_user["id"]) == 2
        assert await repos.items.count_by_owner(test_user["id"], tradable_only=True) == 1


class TestInventoryPresentation:
    def test_item_card_contains_database_id(self):
        from bot.utils.formatters import format_item

        card = format_item({"id": 42, "market_hash_name": "AK-47 | Redline", "price_steam": 12.5}, index=42)

        assert "<code>42</code>" in card
        assert "AK-47 | Redline" in card
