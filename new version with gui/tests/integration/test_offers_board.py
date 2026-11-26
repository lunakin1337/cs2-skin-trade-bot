"""Тесты доски объявлений и каталога скинов."""

import pytest

from bot.handlers.create_offer import (
    cb_draft_publish,
    process_items_offered,
    process_wanted,
)
from bot.handlers.offers import board_view, my_offers_view
from bot.states.trade import TradeStates
from bot.utils.formatters import CARD_INNER, format_offer_card
from tests.helpers import last_text, make_callback, make_message

BOT_ID = 123456789


@pytest.fixture
async def seller(repos, test_user):
    await repos.users.link_steam(
        test_user["id"],
        "76561198000000000",
        "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcd",
        trade_partner="1",
        trade_token="abcd",
    )
    return test_user


@pytest.fixture
async def offer_with_item(repos, seller):
    item_id = await repos.items.add(
        owner_id=seller["id"],
        steam_asset_id="777",
        market_hash_name="★ Ursus Knife | Ultraviolet (Field-Tested)",
        price_steam=92.35,
    )
    offer_id = await repos.offers.create(
        creator_id=seller["id"],
        title="Нож на AWP",
        items_offered=[item_id],
        items_wanted="AWP | Asiimov (Field-Tested)",
        description="обмен сегодня вечером",
        wanted_name="AWP | Asiimov (Field-Tested)",
    )
    return offer_id


class TestOfferCard:
    def test_card_has_fixed_width_and_two_columns(self):
        card = format_offer_card(
            {
                "id": 12,
                "username": "trader",
                "rating": 4.2,
                "description": "обмен сегодня вечером",
                "wanted_name": "AWP | Asiimov (Field-Tested)",
            },
            [{"market_hash_name": "★ Ursus Knife | Ultraviolet (Field-Tested)", "price_steam": 92.35}],
            0,
        )
        lines = card.splitlines()

        assert all(len(line) == CARD_INNER + 2 for line in lines)
        assert "ОТДАЮ" in card and "ХОЧУ" in card
        assert "★ Ursus Knife" in card
        assert "AWP | Asiimov" in card
        assert "#12" in card and "@trader" in card

    def test_card_falls_back_to_free_text(self):
        card = format_offer_card(
            {"id": 1, "username": None, "rating": 0, "items_wanted": "скины на $50"},
            [],
            0,
        )

        assert "скины на $50" in card
        # автор без username/имени больше не раскрывает telegram id
        assert "id " not in card
        assert "Пользователь" in card


class TestBoard:
    async def test_board_renders_offer(self, bot, session, repos, offer_with_item):
        text, markup = await board_view(repos)

        assert "Доска обменов" in text
        assert "Ursus Knife" in text
        assert "AWP | Asiimov" in text
        buttons = [button.text for row in markup.inline_keyboard for button in row]
        assert any("Принять #" in button for button in buttons)

    async def test_my_offers_shows_cancel(self, bot, repos, seller, offer_with_item):
        user = await repos.users.get_by_telegram_id(BOT_ID)
        text, markup = await my_offers_view(repos, user and make_message(bot).from_user)

        assert "Мои предложения" in text
        buttons = [button.text for row in markup.inline_keyboard for button in row]
        assert any("Снять #" in button for button in buttons)


class TestWantedCatalog:
    async def test_free_text_finds_skin_and_publishes(self, bot, repos, state, seller):
        await repos.skins.upsert_many(
            [
                {"market_hash_name": "AWP | Asiimov (Field-Tested)", "price_text": "$118.90", "price_value": 118.9},
                {"market_hash_name": "AWP | Asiimov (Minimal Wear)", "price_text": "$220.00", "price_value": 220.0},
            ]
        )
        item_id = await repos.items.add(
            owner_id=seller["id"],
            steam_asset_id="1",
            market_hash_name="AK-47 | Redline (Field-Tested)",
            price_steam=12.5,
        )

        await state.update_data(item_map={"1": item_id})
        await state.set_state(TradeStates.waiting_items_offered)
        await process_items_offered(make_message(bot, "1"), state, repos)
        assert await state.get_state() == TradeStates.waiting_wanted.state

        await process_wanted(make_message(bot, "асимов мв"), state, repos)

        data = await state.get_data()
        assert data["wanted_name"] == "AWP | Asiimov (Minimal Wear)"
        assert await state.get_state() == TradeStates.waiting_confirm.state

        await cb_draft_publish(make_callback(bot, "draft_publish", BOT_ID), state, repos)

        offers = await repos.offers.get_by_creator(seller["id"])
        assert offers[0]["wanted_name"] == "AWP | Asiimov (Minimal Wear)"
        assert "Asiimov" in offers[0]["title"]

    async def test_price_limit_is_respected(self, bot, repos, state, seller):
        await repos.skins.upsert_many(
            [
                {"market_hash_name": "AWP | Asiimov (Field-Tested)", "price_value": 118.9},
                {"market_hash_name": "AWP | Asiimov (Minimal Wear)", "price_value": 220.0},
            ]
        )
        await state.update_data(item_map={"1": 1}, items_offered=[1], title=None)
        await process_wanted(make_message(bot, "асимов до 150$"), state, repos)

        data = await state.get_data()
        assert data["wanted_name"] == "AWP | Asiimov (Field-Tested)"

    async def test_unknown_query_keeps_step_two(self, bot, repos, state, session, seller):
        await state.set_state(TradeStates.waiting_wanted)
        await state.update_data(item_map={"1": 1}, items_offered=[1])
        await process_wanted(make_message(bot, "несусветный скин"), state, repos)

        assert "не нашёл" in last_text(session)
        assert await state.get_state() == TradeStates.waiting_wanted.state

    async def test_skip_wanted_publishes_without_name(self, bot, repos, state, seller):
        await state.update_data(item_map={"1": 1}, items_offered=[1])
        await state.set_state(TradeStates.waiting_wanted)
        await process_wanted(make_message(bot, "-"), state, repos)

        assert await state.get_state() == TradeStates.waiting_confirm.state
        await cb_draft_publish(make_callback(bot, "draft_publish", BOT_ID), state, repos)

        offers = await repos.offers.get_by_creator(seller["id"])
        assert offers[0]["items_wanted"] == "Не указано"
        assert offers[0]["wanted_name"] is None
