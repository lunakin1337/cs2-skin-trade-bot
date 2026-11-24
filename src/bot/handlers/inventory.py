"""Инвентарь: загрузка из Steam и отображение скинов."""

import logging
import math

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

from bot.keyboards.inline import inventory_keyboard
from bot.services.inventory_sync import sync_inventory
from bot.utils.formatters import (
    format_item,
    format_item_photo_caption,
    format_price,
    item_image_url,
)
from bot.utils.telegram import edit_or_send, notify
from bot.utils.users import ensure_user
from config.settings import BotConfig
from database.repository import Repositories

logger = logging.getLogger(__name__)

router = Router()

PAGE_SIZE = 8
PHOTO_LIMIT = 10


def format_sync_report(report: dict) -> str:
    """Текст отчёта о синхронизации инвентаря."""
    if not report.get("ok"):
        hint = report.get("hint") or report.get("error") or "Неизвестная ошибка"
        return f"❌ Не удалось загрузить инвентарь.\n\n{hint}"

    return "\n".join(
        [
            "✅ <b>Инвентарь синхронизирован</b>",
            "",
            f"Найдено в Steam: {report['found']}",
            f"Добавлено: {report['created']} · обновлено: {report['updated']} · "
            f"удалено: {report['removed']}",
            f"Цены получены для {report['priced']} позиций",
        ]
    )


async def _inventory_view(
    user: dict,
    repos: Repositories,
    page: int = 0,
) -> tuple[str, object]:
    total = await repos.items.count_by_owner(user["id"])
    has_steam = bool(user.get("is_steam_linked"))

    if total == 0:
        text = "\n".join(
            [
                "🎒 <b>Инвентарь пуст</b>",
                "",
                "Скинов в базе пока нет.",
                (
                    "Нажмите «🔄 Синхронизировать», чтобы подтянуть инвентарь CS2 из Steam."
                    if has_steam
                    else "Сначала привяжите Steam-аккаунт в профиле."
                ),
            ]
        )
        return text, inventory_keyboard(has_steam)

    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    items = await repos.items.get_by_owner(user["id"], limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    estimated = await repos.items.sum_price(user["id"])

    lines = [f"🎒 <b>Инвентарь</b> — {total} шт."]
    if estimated:
        lines.append(f"💰 Оценка известных цен: {format_price(estimated)}")
    if user.get("inventory_synced_at"):
        lines.append(f"🔄 Обновлён: {user['inventory_synced_at']} UTC")
    lines.append("")

    for item in items:
        lines.append(format_item(item, index=item["id"]))

    return "\n".join(lines), inventory_keyboard(has_steam, page=page, pages=pages)


async def _show_inventory(
    message: Message,
    repos: Repositories,
    from_user,
    page: int = 0,
    edit: bool = False,
) -> None:
    user = await ensure_user(repos, from_user)
    text, markup = await _inventory_view(user, repos, page)
    if edit:
        await edit_or_send(message, text, markup)
    else:
        await message.answer(text, reply_markup=markup)


@router.message(Command("inventory"))
async def cmd_inventory(message: Message, repos: Repositories, config: BotConfig) -> None:
    await _show_inventory(message, repos, message.from_user)


@router.callback_query(F.data == "inventory")
async def cb_inventory(callback: CallbackQuery, repos: Repositories, config: BotConfig) -> None:
    await _show_inventory(callback.message, repos, callback.from_user, edit=True)
    await notify(callback)


@router.callback_query(F.data.startswith("inv_page_"))
async def cb_inventory_page(callback: CallbackQuery, repos: Repositories, config: BotConfig) -> None:
    try:
        page = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        page = 0
    await _show_inventory(callback.message, repos, callback.from_user, page=page, edit=True)
    await notify(callback)


@router.callback_query(F.data == "inv_noop")
async def cb_inventory_noop(callback: CallbackQuery) -> None:
    await notify(callback)


@router.callback_query(F.data == "inv_photos")
async def cb_inventory_photos(callback: CallbackQuery, repos: Repositories, config: BotConfig) -> None:
    user = await ensure_user(repos, callback.from_user)
    items = await repos.items.get_by_owner(user["id"], limit=PHOTO_LIMIT * 2)

    media = [
        InputMediaPhoto(media=url, caption=format_item_photo_caption(item))
        for item in items
        if (url := item_image_url(item))
    ][:PHOTO_LIMIT]

    if not media:
        await notify(callback, "У предметов нет картинок. Сначала синхронизируйте инвентарь.", alert=True)
        return

    if len(media) == 1:
        await callback.message.answer_photo(media[0].media, caption=media[0].caption)
    else:
        await callback.message.answer_media_group(media)
    await notify(callback, "Картинки отправлены")


@router.callback_query(F.data == "sync_inventory")
async def cb_sync_inventory(callback: CallbackQuery, repos: Repositories, config: BotConfig) -> None:
    user = await ensure_user(repos, callback.from_user)
    if not user.get("is_steam_linked"):
        await notify(callback, "❌ Steam не привязан. Откройте профиль.", alert=True)
        return

    await notify(callback, "Синхронизирую…")
    await edit_or_send(callback.message, "🔄 Загружаю инвентарь из Steam…")

    report = await sync_inventory(repos, user, config)
    user = await repos.users.get_by_id(user["id"])
    text, markup = await _inventory_view(user, repos)
    await edit_or_send(
        callback.message,
        "\n\n———\n\n".join([format_sync_report(report), text]),
        markup,
    )
