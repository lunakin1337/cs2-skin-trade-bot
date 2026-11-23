"""FSM состояния для торговли."""

from aiogram.fsm.state import State, StatesGroup


class TradeStates(StatesGroup):
    waiting_steam_link = State()
    waiting_offer_title = State()
    waiting_offer_description = State()
    waiting_items_offered = State()
    waiting_items_wanted = State()
    confirming_trade = State()


class ProfileStates(StatesGroup):
    waiting_steam_id = State()
    waiting_trade_url = State()