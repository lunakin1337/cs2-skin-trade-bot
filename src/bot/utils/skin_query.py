"""Разбор свободного запроса в понятный каталогу скинов поиск.

Пользователь пишет «асимов мв до 50$» или «нож керамбит» — модуль приводит это
к английским токенам Steam, износу и максимальной цене.
"""

import re
from dataclasses import dataclass, field

# Русские названия оружия/категорий → как они выглядят в Steam
SYNONYMS: dict[str, str] = {
    "нож": "★",
    "ножи": "★",
    "ножик": "★",
    "knife": "★",
    "knives": "★",
    "перчатки": "★ gloves",
    "перчатка": "★ gloves",
    "перчатк": "★ gloves",
    "gloves": "★ gloves",
    "стикер": "Sticker",
    "стикеры": "Sticker",
    "наклейка": "Sticker",
    "наклейки": "Sticker",
    "sticker": "Sticker",
    "граффити": "Graffiti",
    "graffiti": "Graffiti",
    "капсула": "Capsule",
    "капсулы": "Capsule",
    "caspule": "Capsule",
    "кейс": "Case",
    "кейсы": "Case",
    "case": "Case",
    "асимов": "Asiimov",
    "азимов": "Asiimov",
    "асимо": "Asiimov",
    "керамбит": "Karambit",
    "керамбита": "Karambit",
    "карамбит": "Karambit",
    "бабочка": "Butterfly",
    "бабочку": "Butterfly",
    "гут": "Gut",
    "флип": "Flip",
    "баёнет": "Bayonet",
    "байонет": "Bayonet",
    "штык": "Bayonet",
    "тальон": "Talon",
    "медвежий": "Ursus",
    "урсус": "Ursus",
    "мамба": "M9",
    "красная": "Redline",
    "редлайн": "Redline",
    "неонуар": "Neo-Noir",
    "катовице": "Katowice",
    "катовіце": "Katowice",
    "катовица": "Katowice",
    "хайпер": "Hyper Beast",
    "хайпербист": "Hyper Beast",
    "доплер": "Doppler",
    "допплер": "Doppler",
    "поток": "Printstream",
    "феид": "Fade",
    "фейд": "Fade",
    "кейсхарден": "Case Hardened",
    "кейс харден": "Case Hardened",
    "нео-нуар": "Neo-Noir",
    "принтстрим": "Printstream",
    "принт": "Printstream",
    "дыхание": "Breeze",
    "дыхание тропиков": "Tropical Breeze",
    "дракон": "Dragon Lore",
    "лоре": "Dragon Lore",
    "длор": "Dragon Lore",
    "дуплет": "Dual Berettas",
    "дуалберетты": "Dual Berettas",
    "дуал": "Dual Berettas",
    "деagle": "Desert Eagle",
    "дигл": "Desert Eagle",
    "мка": "M4A4",
    "эмка": "M4A4",
    "эм4": "M4A1-S",
    "калаш": "AK-47",
    "ак": "AK-47",
    "ак47": "AK-47",
    "аwp": "AWP",
    "авп": "AWP",
    "авик": "AWP",
    "юспи": "USP-S",
    "юсп": "USP-S",
    "глок": "Glock-18",
    "глок18": "Glock-18",
    "тек9": "Tec-9",
    "фамас": "FAMAS",
    "галил": "Galil AR",
    "автомат": "",
}

WEAR_PHRASES: dict[str, str] = {
    "прямо с завода": "Factory New",
    "немного поношенное": "Minimal Wear",
    "после полевых испытаний": "Field-Tested",
    "закалённое в боях": "Battle-Scarred",
    "закаленное в боях": "Battle-Scarred",
    "поношенное": "Well-Worn",
}

WEAR_CODES: dict[str, str] = {
    "фн": "Factory New",
    "fn": "Factory New",
    "мв": "Minimal Wear",
    "mw": "Minimal Wear",
    "фт": "Field-Tested",
    "ft": "Field-Tested",
    "вв": "Well-Worn",
    "ww": "Well-Worn",
    "бс": "Battle-Scarred",
    "bs": "Battle-Scarred",
    "бт": "Battle-Scarred",
    "bt": "Battle-Scarred",
}

STATTRAK_WORDS = ("stattrak", "стт", "ст", "st", "статтрак")

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

PRICE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:\$|usd|долл\w*|бакс\w*|уе|евро|eur)", re.I)
WORD_RE = re.compile(r"[0-9a-zа-яё★|-]+", re.I)

STOP_WORDS = {
    "и", "в", "на", "за", "до", "с", "по", "или", "мне", "хочу", "нужен",
    "нужна", "нужно", "скин", "скины", "скинов", "обмен", "обменяю", "любой",
    "любые", "что", "то", "похож", "типа", "около", "примерно",
}


def transliterate(text: str) -> str:
    return "".join(TRANSLIT.get(char, char) for char in text)


@dataclass
class SkinQuery:
    """Разобранный запрос пользователя."""

    raw: str
    tokens: list[str] = field(default_factory=list)
    wear: str | None = None
    max_price: float | None = None
    stattrak: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.tokens and self.max_price is None


def parse_query(raw: str) -> SkinQuery:
    """Разобрать свободный текст: синонимы, износ, цена, StatTrak."""
    text = (raw or "").lower().strip()
    query = SkinQuery(raw=raw or "")

    price_match = PRICE_RE.search(text)
    if price_match:
        query.max_price = float(price_match.group(1).replace(",", "."))
        text = PRICE_RE.sub(" ", text)

    for phrase, wear in WEAR_PHRASES.items():
        if phrase in text:
            query.wear = wear
            text = text.replace(phrase, " ")

    for word, mapped in SYNONYMS.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            if not mapped:
                text = re.sub(rf"\b{re.escape(word)}\b", " ", text)
                continue
            text = re.sub(rf"\b{re.escape(word)}\b", f" {mapped} ", text)

    words = [word for word in WORD_RE.findall(text) if word not in {"-"}]
    tokens: list[str] = []
    for word in words:
        if word in STOP_WORDS:
            continue
        if word in WEAR_CODES:
            query.wear = WEAR_CODES[word]
            continue
        if word in STATTRAK_WORDS:
            query.stattrak = True
            continue
        if re.fullmatch(r"[а-яё]+", word):
            word = transliterate(word)
        tokens.append(word)

    query.tokens = tokens[:6]
    return query
