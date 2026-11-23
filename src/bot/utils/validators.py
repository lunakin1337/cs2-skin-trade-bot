"""Валидация пользовательского ввода."""

import re

from bot.utils.steam import parse_trade_url

STEAM_ID64_PATTERN = re.compile(r"^7656119\d{10}$")


def validate_steam_id64(steam_id: str | None) -> tuple[bool, str | None]:
    """Проверить SteamID64 (17 цифр, начинается с 7656119)."""
    if not steam_id:
        return False, "SteamID64 не может быть пустым"

    steam_id = steam_id.strip()
    if not steam_id.isdigit():
        return False, "SteamID64 состоит только из цифр"
    if len(steam_id) != 17:
        return False, f"SteamID64 должен содержать 17 цифр (сейчас {len(steam_id)})"
    if not STEAM_ID64_PATTERN.match(steam_id):
        return False, "SteamID64 должен начинаться с 7656119"

    return True, None


def validate_trade_url(trade_url: str | None) -> tuple[bool, str | None]:
    """Проверить Steam Trade URL."""
    if not trade_url:
        return False, "Ссылка на обмен не может быть пустой"
    if parse_trade_url(trade_url) is None:
        return (
            False,
            "Неверная ссылка. Ожидается https://steamcommunity.com/tradeoffer/new/?partner=123456&token=ABCDEF",
        )
    return True, None
