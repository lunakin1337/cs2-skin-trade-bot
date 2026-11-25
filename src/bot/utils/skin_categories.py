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


# Редкость: слаг -> цвет из Steam Market (`asset_description.name_color`).
RARITY_BY_COLOR = {
    "b0c3d9": "consumer",
    "5e98d9": "industrial",
    "4b69ff": "milspec",
    "8847ff": "restricted",
    "d32ce6": "classified",
    "eb4b4b": "covert",
    "f0b90b": "rare",
    "e4ae39": "contraband",
    "d2d2d2": "consumer",
    "3e4a54": "consumer",
}

# Редкость по тексту типа предмета («Covert Rifle», «Classified Pistol», «★ Knife»).
RARITY_BY_TYPE = (
    ("contraband", "contraband"),
    ("covert", "covert"),
    ("classified", "classified"),
    ("restricted", "restricted"),
    ("mil-spec", "milspec"),
    ("milspec", "milspec"),
    ("industrial", "industrial"),
    ("consumer", "consumer"),
)


def rarity_from_market(name_color: str | None, type_text: str | None = None, name: str = "") -> str | None:
    """Редкость скина из ответа Steam Market: по цвету, затем по типу, затем по ★."""
    # Текст типа и «★» точнее цвета: у ножей цвет тот же, что у covert, а редкость rare.
    lowered = (type_text or "").strip().lower()
    for needle, rarity in RARITY_BY_TYPE:
        if needle in lowered:
            return rarity

    if (name or "").strip().startswith("★"):
        return "rare"

    color = (name_color or "").strip().lstrip("#").lower()
    return RARITY_BY_COLOR.get(color)


# Основы слов: редкость приходит из тегов Steam и по-русски, и по-английски,
# причём в разных формах («Засекреченное», «засекреченного типа», «Classified»).
_RARITY_STEMS: tuple[tuple[str, str], ...] = (
    ("контрабанд", "contraband"),
    ("contraband", "contraband"),
    ("тайное", "covert"),
    ("covert", "covert"),
    ("засекреч", "classified"),
    ("classified", "classified"),
    ("экзотич", "classified"),
    ("exotic", "classified"),
    ("запрещ", "restricted"),
    ("restricted", "restricted"),
    ("примечательн", "restricted"),
    ("remarkable", "restricted"),
    ("армейск", "milspec"),
    ("mil-spec", "milspec"),
    ("milspec", "milspec"),
    ("превосходн", "milspec"),
    ("superior", "milspec"),
    ("промышлен", "industrial"),
    ("industrial", "industrial"),
    ("высшего класса", "industrial"),
    ("high grade", "industrial"),
    ("ширпотреб", "consumer"),
    ("базового класса", "consumer"),
    ("стандартн", "consumer"),
    ("consumer", "consumer"),
    ("base grade", "consumer"),
    ("экстраординар", "rare"),
    ("extraordinary", "rare"),
    ("rare", "rare"),
)


def rarity_slug(rarity: str | None, name: str = "") -> str | None:
    """Привести редкость из тегов Steam (рус/англ) к слагу каталога."""
    value = (rarity or "").strip().lower()
    if not value:
        return "rare" if (name or "").strip().startswith("★") else None
    for stem, slug in _RARITY_STEMS:
        if stem in value:
            return slug
    return None
