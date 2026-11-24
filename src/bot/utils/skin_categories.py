"""Категории и оружие CS2 для навигации по каталогу (как на маркетплейсах)."""

import re

CATEGORY_ORDER = (
    "rifles",
    "snipers",
    "smg",
    "pistols",
    "heavy",
    "knives",
    "gloves",
    "agents",
    "zeus",
    "stickers",
    "graffiti",
    "music",
    "cases",
    "other",
)

WEAPONS: dict[str, tuple[str, ...]] = {
    "pistols": (
        "Glock-18",
        "USP-S",
        "P2000",
        "P250",
        "Dual Berettas",
        "Five-SeveN",
        "Tec-9",
        "CZ75-Auto",
        "Desert Eagle",
        "R8 Revolver",
    ),
    "smg": ("MAC-10", "MP9", "MP7", "MP5-SD", "UMP-45", "P90", "PP-Bizon"),
    "rifles": ("AK-47", "M4A4", "M4A1-S", "FAMAS", "Galil AR", "AUG", "SG 553"),
    "snipers": ("SSG 08", "AWP", "SCAR-20", "G3SG1"),
    "heavy": ("Nova", "XM1014", "MAG-7", "Sawed-Off", "M249", "Negev"),
}

CATEGORY_TITLES = {
    "rifles": ("Винтовки", "🎯"),
    "snipers": ("Снайперские", "🔭"),
    "smg": ("Пистолеты-пулемёты", "🔩"),
    "pistols": ("Пистолеты", "🔫"),
    "heavy": ("Тяжёлое", "💥"),
    "knives": ("Ножи", "🗡"),
    "gloves": ("Перчатки", "🧤"),
    "agents": ("Агенты", "🕵️"),
    "zeus": ("Zeus", "⚡"),
    "stickers": ("Стикеры", "🏷"),
    "graffiti": ("Граффити", "🎨"),
    "music": ("Музыка", "🎵"),
    "cases": ("Кейсы и капсулы", "📦"),
    "other": ("Прочее", "❔"),
}

_WEAPON_LOOKUP = {
    weapon.lower(): (category, weapon)
    for category, weapons in WEAPONS.items()
    for weapon in weapons
}

_STICKER_PREFIXES = ("sticker", "sealed graffiti", "graffiti", "music kit", "agent", "case", "capsule")


def classify(market_hash_name: str) -> tuple[str, str | None]:
    """(категория, оружие) по имени предмета из Steam."""
    name = (market_hash_name or "").strip()
    lowered = name.lower()

    if lowered.startswith("★"):
        if "gloves" in lowered or "hand wraps" in lowered:
            return "gloves", None
        return "knives", None

    if lowered.startswith("sticker"):
        return "stickers", None
    if "graffiti" in lowered:
        return "graffiti", None
    if lowered.startswith("music kit"):
        return "music", None
    if lowered.startswith("agent") or " | agent" in lowered:
        return "agents", None
    if "zeus" in lowered:
        return "zeus", None
    if lowered.startswith(("case", "capsule")) or "ключ" in lowered:
        return "cases", None

    # «StatTrak™ AK-47 | Redline», «Souvenir AWP | ...» — префикс не мешает оружию
    cleaned = re.sub(r"^(statTrak™?|souvenir)\s+", "", name, flags=re.I)
    head = re.split(r"\s*\|\s*", cleaned, maxsplit=1)[0].strip().lower()
    if head in _WEAPON_LOOKUP:
        return _WEAPON_LOOKUP[head]

    for weapon_key, (category, weapon) in _WEAPON_LOOKUP.items():
        if cleaned.lower().startswith(weapon_key):
            return category, weapon

    return "other", None


def category_title(code: str) -> str:
    title, emoji = CATEGORY_TITLES.get(code, ("Прочее", "❔"))
    return f"{emoji} {title}"
