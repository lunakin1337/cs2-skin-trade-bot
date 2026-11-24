"""Интеграционные тесты хендлеров.

Сессия-заглушка записывает вызовы Telegram API вместо отправки.
"""

from tests.helpers import alerts, last_text, make_callback, make_message


class TestStartHandler:
    async def test_start_creates_user(self, bot, session, repos, config):
        from bot.handlers.start import cmd_start

        await cmd_start(make_message(bot), repos, config)

        user = await repos.users.get_by_telegram_id(123456789)
        assert user is not None
        assert user["username"] == "testuser"
        assert "добро пожаловать" in last_text(session)

    async def test_help(self, bot, session):
        from bot.handlers.start import cmd_help

        await cmd_help(make_message(bot, "/help"))

        assert "справка" in last_text(session)

    async def test_main_menu_callback(self, bot, session, state, config):
        from bot.handlers.start import cb_main_menu

        await cb_main_menu(make_callback(bot, "main_menu"), state, config)

        assert "меню" in last_text(session)


class TestProfile:
    async def test_profile_without_steam(self, bot, session, repos, config):
        from bot.handlers.profile import cmd_profile

        await cmd_profile(make_message(bot, "/profile"), repos, config)

        text = last_text(session)
        assert "профиль" in text
        assert "не привязан" in text

    async def test_profile_callback(self, bot, session, repos, config):
        from bot.handlers.profile import cb_profile

        await cb_profile(make_callback(bot, "profile"), repos, config)

        assert "профиль" in last_text(session)

    async def test_steam_id_validation(self, bot, session, state, config):
        from bot.handlers.profile import process_steam_id

        await process_steam_id(make_message(bot, "12345"), state, config)

        assert "17 цифр" in last_text(session)
        assert await state.get_state() is None

    async def test_trade_url_validation(self, bot, session, state, repos):
        from bot.handlers.profile import process_trade_url

        await state.update_data(steam_id="76561198000000000")
        await process_trade_url(make_message(bot, "https://example.com"), state, repos)

        assert "неверная ссылка" in last_text(session)

    async def test_full_steam_link(self, bot, session, state, repos, config):
        from bot.handlers.profile import process_steam_id, process_trade_url

        await process_steam_id(make_message(bot, "76561198000000000"), state, config)
        await process_trade_url(
            make_message(
                bot,
                "https://steamcommunity.com/tradeoffer/new/?partner=123456&token=AbCdEf",
            ),
            state,
            repos,
        )

        user = await repos.users.get_by_telegram_id(123456789)
        assert user["is_steam_linked"] == 1
        assert user["steam_id"] == "76561198000000000"
        assert user["steam_trade_partner"] == "123456"
        assert user["steam_trade_token"] == "AbCdEf"


class TestInventory:
    async def test_inventory_empty(self, bot, session, repos, config):
        from bot.handlers.inventory import cmd_inventory

        await cmd_inventory(make_message(bot, "/inventory"), repos, config)

        assert "инвентарь" in last_text(session)

    async def test_sync_requires_steam(self, bot, session, repos, config):
        from bot.handlers.inventory import cb_sync_inventory

        await cb_sync_inventory(make_callback(bot, "sync_inventory"), repos, config)

        assert any(alert for alert in alerts(session))

    async def test_inventory_pagination(self, bot, session, repos, config, test_user):
        from bot.handlers.inventory import cb_inventory_page

        for index in range(3):
            await repos.items.add(
                owner_id=test_user["id"],
                steam_asset_id=str(index),
                market_hash_name=f"Skin {index}",
                price_steam=10.0 + index,
            )

        await cb_inventory_page(make_callback(bot, "inv_page_0"), repos, config)

        text = last_text(session)
        assert "инвентарь" in text
        assert "skin" in text


class TestOffers:
    async def test_offers_empty(self, bot, session, repos):
        from bot.handlers.offers import cmd_offers

        await cmd_offers(make_message(bot, "/offers"), repos)

        assert "предложений обмена нет" in last_text(session)

    async def test_accept_own_offer_denied(self, bot, session, repos, test_user):
        from bot.handlers.trade_flow import cb_accept_offer

        offer_id = await repos.offers.create(
            creator_id=test_user["id"],
            title="Обмен",
            items_offered=[],
            items_wanted="нож",
        )

        await cb_accept_offer(make_callback(bot, f"accept_offer_{offer_id}"), repos)

        assert any("своё" in alert for alert in alerts(session))


class TestAdmin:
    async def test_admin_panel_allowed(self, bot, session, repos, config):
        from bot.handlers.admin import cmd_admin

        await cmd_admin(make_message(bot, "/admin", 8851272459, "admin"), repos, config)

        assert "админ" in last_text(session)

    async def test_admin_denied(self, bot, session, repos, config):
        from bot.handlers.admin import cmd_admin

        await cmd_admin(make_message(bot, "/admin", 999999999, "hacker"), repos, config)

        assert "нет прав" in last_text(session)


class TestCreateOffer:
    async def test_requires_steam(self, bot, session, repos, state):
        from bot.handlers.create_offer import cmd_create_offer

        await cmd_create_offer(make_message(bot, "/create_offer"), state, repos)

        assert "steam" in last_text(session)
        assert await state.get_state() is None


    async def test_numbering_maps_to_hidden_ids(self, bot, repos, state, test_user):
        from bot.handlers.create_offer import process_items_offered, process_offer_description

        await repos.users.link_steam(
            test_user["id"],
            "76561198000000000",
            "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcd",
            trade_partner="1",
            trade_token="abcd",
        )
        for index in range(3):
            await repos.items.add(
                owner_id=test_user["id"],
                steam_asset_id=str(index),
                market_hash_name=f"Skin {index}",
                price_steam=10.0 + index,
            )

        await state.update_data(title="Тест")
        await process_offer_description(make_message(bot, "описание"), state, repos)

        data = await state.get_data()
        assert set(data["item_map"]) == {"1", "2", "3"}

        await process_items_offered(make_message(bot, "2"), state, repos)
        data = await state.get_data()
        assert data["items_offered"] == [data["item_map"]["2"]]

    async def test_locked_items_leave_numbering_gaps(self, bot, repos, state, test_user):
        from bot.handlers.create_offer import process_offer_description

        await repos.users.link_steam(
            test_user["id"],
            "76561198000000000",
            "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcd",
            trade_partner="1",
            trade_token="abcd",
        )
        await repos.items.add(
            owner_id=test_user["id"],
            steam_asset_id="1",
            market_hash_name="Дорогой скин",
            price_steam=100.0,
        )
        await repos.items.add(
            owner_id=test_user["id"],
            steam_asset_id="2",
            market_hash_name="Заблокированный",
            price_steam=50.0,
            is_tradable=False,
        )

        await state.update_data(title="Тест")
        await process_offer_description(make_message(bot, "описание"), state, repos)

        data = await state.get_data()
        assert set(data["item_map"]) == {"1"}

    async def test_unknown_number_rejected(self, bot, repos, state, session, test_user):
        from bot.handlers.create_offer import process_items_offered

        await state.update_data(item_map={"1": 123})
        await process_items_offered(make_message(bot, "99"), state, repos)

        data = await state.get_data()
        assert "items_offered" not in data
        assert "нет в списке" in last_text(session)
