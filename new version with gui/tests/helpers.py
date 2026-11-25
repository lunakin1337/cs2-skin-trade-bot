"""Общие помощники интеграционных тестов."""

from aiogram import Bot
from aiogram.methods.base import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, User

TEXT_METHODS = {"SendMessage", "EditMessageText", "SendPhoto"}


class RecordingSession:
    """Сессия-заглушка: записывает вызовы вместо отправки."""

    def __init__(self):
        self.calls: list[TelegramMethod] = []

    async def __call__(self, bot: Bot, method: TelegramMethod, timeout=None):
        self.calls.append(method)
        return type("R", (), {"message_id": 1})()

    async def close(self):
        pass


def user(user_id: int = 123456789, username: str = "testuser") -> User:
    return User(id=user_id, is_bot=False, first_name="Test", username=username)


def chat(chat_id: int = 123456789) -> Chat:
    return Chat(id=chat_id, type="private")


def make_message(
    bot: Bot,
    text: str = "/start",
    user_id: int = 123456789,
    username: str = "testuser",
) -> Message:
    return Message(
        message_id=1,
        date=1234567890,
        chat=chat(user_id),
        from_user=user(user_id, username),
        text=text,
    ).as_(bot)


def make_callback(
    bot: Bot,
    data: str,
    user_id: int = 123456789,
    username: str = "testuser",
) -> CallbackQuery:
    return CallbackQuery(
        id="cb",
        from_user=user(user_id, username),
        chat_instance="test",
        data=data,
        message=make_message(bot, text="меню", user_id=user_id, username=username),
    ).as_(bot)


def last_text(session: RecordingSession) -> str:
    """Текст последнего сообщения или подписи к фото."""
    for call in reversed(session.calls):
        if type(call).__name__ in TEXT_METHODS:
            text = getattr(call, "text", None) or getattr(call, "caption", None) or ""
            return text.lower()
    raise AssertionError("хендлер не отправил ни одного сообщения")


def alerts(session: RecordingSession) -> list[str]:
    return [
        (call.text or "")
        for call in session.calls
        if type(call).__name__ == "AnswerCallbackQuery"
    ]
