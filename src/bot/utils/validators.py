"""Validators for the bot."""

import re
from typing import Optional


# Regular expressions
STEAM_ID64_PATTERN = re.compile(r"^7656119\d{10}$")  # 17 digits, starts with 7656119
TRADE_URL_PATTERN = re.compile(
    r"^https://steamcommunity\.com/tradeoffer/new/\?partner=\d+&token=[a-zA-Z0-9_-]+$"
)
FLOAT_VALUE_PATTERN = re.compile(r"^(0\.\d+|1\.0?)$")  # 0.0 - 1.0
PAINT_SEED_PATTERN = re.compile(r"^\d{1,4}$")  # 0-9999


def validate_steam_id64(steam_id: str) -> tuple[bool, Optional[str]]:
    """
    Validate SteamID64.

    Returns:
        (is_valid, error_message)
    """
    if not steam_id:
        return False, "SteamID64 cannot be empty"

    steam_id = steam_id.strip()

    if not steam_id.isdigit():
        return False, "SteamID64 must contain only digits"

    if len(steam_id) != 17:
        return False, f"SteamID64 must be 17 digits (got {len(steam_id)})"

    if not STEAM_ID64_PATTERN.match(steam_id):
        return False, "SteamID64 must start with 7656119"

    return True, None


def validate_trade_url(trade_url: str) -> tuple[bool, Optional[str]]:
    """
    Validate Steam Trade URL.

    Returns:
        (is_valid, error_message)
    """
    if not trade_url:
        return False, "Trade URL cannot be empty"

    trade_url = trade_url.strip()

    if not trade_url.startswith("https://steamcommunity.com/tradeoffer/new/"):
        return False, "Trade URL must start with https://steamcommunity.com/tradeoffer/new/"

    if not TRADE_URL_PATTERN.match(trade_url):
        return False, "Invalid Trade URL format. Expected: https://steamcommunity.com/tradeoffer/new/?partner=123456&token=ABCDEF"

    return True, None


def validate_float_value(float_str: str) -> tuple[bool, Optional[str], Optional[float]]:
    """
    Validate float value (wear).

    Returns:
        (is_valid, error_message, float_value)
    """
    if not float_str:
        return False, "Float value cannot be empty", None

    try:
        value = float(float_str)
    except ValueError:
        return False, "Float value must be a number", None

    if value < 0.0 or value > 1.0:
        return False, "Float value must be between 0.0 and 1.0", None

    return True, None, value


def validate_paint_seed(seed_str: str) -> tuple[bool, Optional[str], Optional[int]]:
    """
    Validate paint seed.

    Returns:
        (is_valid, error_message, paint_seed)
    """
    if not seed_str:
        return False, "Paint seed cannot be empty", None

    if not seed_str.isdigit():
        return False, "Paint seed must be a number", None

    value = int(seed_str)
    if value < 0 or value > 9999:
        return False, "Paint seed must be between 0 and 9999", None

    return True, None, value


def validate_market_hash_name(name: str) -> tuple[bool, Optional[str]]:
    """Validate market_hash_name."""
    if not name:
        return False, "Item name cannot be empty"

    if len(name) > 200:
        return False, "Name too long (max 200 characters)"

    # Basic check for suspicious characters
    if any(c in name for c in ['<', '>', '&', '"', "'"]):
        return False, "Name contains invalid characters"

    return True, None


def validate_item_amount(amount_str: str, max_amount: int = 10) -> tuple[bool, Optional[str], Optional[int]]:
    """Validate item amount."""
    if not amount_str:
        return False, "Amount cannot be empty", None

    if not amount_str.isdigit():
        return False, "Amount must be a number", None

    value = int(amount_str)
    if value < 1:
        return False, "Amount must be at least 1", None

    if value > max_amount:
        return False, f"Amount cannot exceed {max_amount}", None

    return True, None, value


def validate_trade_title(title: str) -> tuple[bool, Optional[str]]:
    """Validate trade offer title."""
    if not title:
        return False, "Title cannot be empty"

    title = title.strip()
    if len(title) < 3:
        return False, "Title too short (min 3 characters)"

    if len(title) > 100:
        return False, "Title too long (max 100 characters)"

    return True, None


def validate_trade_description(desc: str) -> tuple[bool, Optional[str]]:
    """Validate trade offer description."""
    if desc is None:
        return True, None  # Description is optional

    if len(desc) > 1000:
        return False, "Description too long (max 1000 characters)"

    return True, None


def sanitize_html(text: str) -> str:
    """Escape HTML for safe output in Telegram."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def format_price_usd(price: Optional[float]) -> str:
    """Format price in USD."""
    if price is None:
        return "-"
    if price >= 1000:
        return f"${price:,.2f}"
    return f"${price:.2f}"


def format_price_rub(price: Optional[float], usd_to_rub: float = 95.0) -> str:
    """Format price in RUB (approximate rate)."""
    if price is None:
        return "-"
    rub = price * usd_to_rub
    if rub >= 1000:
        return f"{rub:,.0f} RUB"
    return f"{rub:.0f} RUB"