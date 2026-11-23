"""FSM-состояния."""

from aiogram.fsm.state import State, StatesGroup


class TradeStates(StatesGroup):
    """Создание предложения обмена."""

    waiting_offer_title = State()
    waiting_offer_description = State()
    waiting_items_offered = State()
    waiting_items_wanted = State()


class ProfileStates(StatesGroup):
    """Привязка Steam."""

    waiting_steam_id = State()
    waiting_trade_url = State()
