"""Хендеры инвентаря скинов."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from database.repository import Repositories
from bot.keyboards.inline import back_to_main_keyboard, inventory_keyboard
from bot.utils.steam import get_steam_api, SteamAPIError

router = Router()


@router.message(Command("inventory"))
async def cmd_inventory(message: Message, repos: Repositories) -> None:
    await _show_inventory(message, repos, is_callback=False)


@router.callback_query(F.data == "inventory")
async def cb_inventory(callback: CallbackQuery, repos: Repositories) -> None:
    await _show_inventory(callback, repos, is_callback=True)


async def _show_inventory(event: Message | CallbackQuery, repos: Repositories, is_callback: bool) -> None:
    user = await repos.users.get_by_telegram_id(event.from_user.id)
    if not user:
        if is_callback:
            await event.answer("Пользователь не найден")
        return

    items = await repos.items.get_by_owner(user["id"], tradable_only=True)
    has_steam = user.get("is_steam_linked", False)

    if not items:
        text = (
            "🎒 <b>Инвентарь пуст</b>\n\n"
            "У вас нет торгуемых скинов."
        )
        if has_steam:
            text += "\nНажмите «Синхронизировать с Steam» для загрузки инвентаря."
        else:
            text += "\nСначала привяжите Steam в профиле."
        
        if is_callback:
            await event.message.edit_text(text, reply_markup=inventory_keyboard(has_steam))
            await event.answer()
        else:
            await event.answer(text, reply_markup=inventory_keyboard(has_steam))
        return

    text = "🎒 <b>Ваш инвентарь</b>\n\n"
    for item in items[:10]:
        text += (
            f"• {item.get('market_hash_name', 'Неизвестный предмет')}\n"
            f"  Качество: {item.get('quality') or '-'}\n"
            f"  Float: {item.get('float_value') or '-'}\n"
            f"  Цена: ${item.get('price_steam') or 0:.2f}\n\n"
        )

    if len(items) > 10:
        text += f"... и ещё {len(items) - 10} предметов"

    if is_callback:
        await event.message.edit_text(text, reply_markup=inventory_keyboard(has_steam))
        await event.answer()
    else:
        await event.answer(text, reply_markup=inventory_keyboard(has_steam))


@router.callback_query(F.data == "sync_inventory")
async def cb_sync_inventory(callback: CallbackQuery, repos: Repositories) -> None:
    user = await repos.users.get_by_telegram_id(callback.from_user.id)
    if not user or not user.get("is_steam_linked"):
        await callback.answer("❌ Steam не привязан", show_alert=True)
        return

    await callback.message.edit_text("🔄 <b>Синхронизация с Steam...</b>\n\nПолучение инвентаря, подождите...")
    await callback.answer()

    steam_id = user.get("steam_id")
    if not steam_id:
        await callback.message.edit_text("❌ Steam ID не найден в профиле", reply_markup=back_to_main_keyboard())
        return

    try:
        steam_api = await get_steam_api()
        inventory = await steam_api.get_player_inventory(steam_id)
        
        if not inventory.success:
            error = inventory.error or "Неизвестная ошибка"
            await callback.message.edit_text(
                f"❌ Ошибка синхронизации: {error}\n\n"
                "Возможные причины:\n"
                "• Инвентарь приватный (нужен Steam API Key)\n"
                "• Неверный Steam ID\n"
                "• Временные проблемы с Steam API",
                reply_markup=inventory_keyboard(True)
            )
            return

        # Обогащаем предметы данными из схемы
        items = await steam_api.resolve_item_details(inventory.items)

        # Сохраняем в БД
        saved_count = 0
        for item in items:
            if item.market_hash_name:
                await repos.items.create_or_update(
                    owner_id=user["id"],
                    asset_id=item.asset_id,
                    class_id=item.class_id,
                    instance_id=item.instance_id,
                    market_hash_name=item.market_hash_name,
                    market_name=item.market_name,
                    name=item.name,
                    type=item.type,
                    quality=item.quality,
                    float_value=item.float_value,
                    paint_seed=item.paint_seed,
                    stickers=item.stickers,
                    tradable=item.tradable,
                    marketable=item.marketable,
                )
                saved_count += 1

        await callback.message.edit_text(
            f"✅ <b>Синхронизация завершена!</b>\n\n"
            f"Получено предметов: {inventory.total_count}\n"
            f"Сохранено в БД: {saved_count}\n\n"
            "Теперь вы можете просматривать инвентарь и создавать предложения.",
            reply_markup=inventory_keyboard(True)
        )

    except SteamAPIError as e:
        await callback.message.edit_text(
            f"❌ Ошибка Steam API: {e}",
            reply_markup=inventory_keyboard(True)
        )
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Неожиданная ошибка: {e}",
            reply_markup=inventory_keyboard(True)
        )