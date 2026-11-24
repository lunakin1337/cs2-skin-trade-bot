"""FSM-состояния."""

from aiogram.fsm.state import State, StatesGroup


class TradeStates(StatesGroup):
    """Создание предложения обмена за три шага."""

    waiting_items_offered = State()
    waiting_wanted = State()
    waiting_confirm = State()


class DisputeStates(StatesGroup):
    """Открытие спора: ждём причину текстом."""

    waiting_reason = State()


class ProfileStates(StatesGroup):
    """Привязка Steam."""

    waiting_steam_id = State()
    waiting_trade_url = State()
