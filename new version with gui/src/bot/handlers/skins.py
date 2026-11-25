"""Раздел каталога скинов: текстовая база всех скинов CS2."""

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import back_to_main_keyboard
from bot.utils.formatters import NEWLINE
from bot.utils.telegram import edit_or_send, notify
from database.repository import Repositories

router = Router()

CATALOG_LIMIT = 10

USAGE = (
    "🧾 <b>Каталог скинов</b>"
    + NEWLINE * 2
    + "Текстовая база CS2 — по ней бот ищет «хочу» при создании предложения."
    + NEWLINE * 2
    + "Напишите запрос одним сообщением или командой:"
    + NEWLINE
    + "<code>/skins awp asiimov</code>"
    + NEWLINE
    + "<code>/skins ★ karambit</code>"
    + NEWLINE
    + "<code>/skins sticker katowice</code>"
)


async def _render(repos: Repositories, query: str) -> str:
    if not query.strip():
        return USAGE

    skins = await repos.skins.search(query, limit=CATALOG_LIMIT)
    total = await repos.skins.count()

    if not skins:
        return (
            f"🧾 По запросу «{query}» ничего не нашлось."
            + NEWLINE * 2
            + f"В каталоге {total} позиций. Попробуйте короче: «asiimov», «doppler», «sticker»."
        )

    lines = [f"🧾 <b>Каталог</b> · «{query}» · всего в базе {total}", ""]
    for index, skin in enumerate(skins, start=1):
        price = f" · {skin['price_text']}" if skin.get("price_text") else ""
        lines.append(f"<code>{index}</code>. {skin['market_hash_name']}{price}")

    lines.append("")
    lines.append("Чтобы это скинуть в «хочу» — создайте предложение: /create_offer")
    return NEWLINE.join(lines)


@router.message(Command("skins"))
async def cmd_skins(message: Message, command: CommandObject, repos: Repositories) -> None:
    await message.answer(
        await _render(repos, command.args or ""),
        reply_markup=back_to_main_keyboard(),
    )


@router.callback_query(F.data == "skins")
async def cb_skins(callback: CallbackQuery, repos: Repositories) -> None:
    await edit_or_send(callback.message, USAGE, back_to_main_keyboard())
    await notify(callback)
