"""Хендеры трейд-флоу (Срез 8) - создание сделок и подтверждение."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from database.repository import Repositories
from bot.keyboards.inline import back_to_main_keyboard

router = Router()


@router.message(Command("trade"))
async def cmd_trade_info(message: Message) -> None:
    await message.answer(
        "🔄 <b>Трейд-флоу</b>\n\n"
        "Чтобы начать сделку:\n"
        "1. Найдите предложение в /offers\n"
        "2. Ответьте на него — бот создаст сделку\n"
        "3. Обе стороны подтверждают обмен\n"
        "4. Скины передаются через эскроу\n\n"
        "Команды:\n"
        "/trades — ваши сделки\n"
        "/create_offer — создать предложение",
        reply_markup=back_to_main_keyboard(),
    )


@router.callback_query(F.data.startswith("accept_offer_"))
async def cb_accept_offer(callback: CallbackQuery, repos: Repositories) -> None:
    offer_id = int(callback.data.split("_")[-1])
    offer = await repos.offers.get_by_id(offer_id)

    if not offer:
        await callback.answer("Предложение не найдено")
        return

    if offer["status"] != "active":
        await callback.answer("Предложение больше не активно")
        return

    user = await repos.users.get_by_telegram_id(callback.from_user.id)
    if not user:
        await repos.users.create_or_update(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
        )
        user = await repos.users.get_by_telegram_id(callback.from_user.id)

    if user["id"] == offer["creator_id"]:
        await callback.answer("Вы не можете принять своё собственное предложение")
        return

    # Создаём сделку
    trade_id = await repos.trades.create(
        buyer_id=user["id"],
        seller_id=offer["creator_id"],
        offer_id=offer_id,
    )

    # Добавляем предметы в сделку
    import json
    items_offered = json.loads(offer["items_offered"])
    for item_id in items_offered:
        await repos.trade_items.add(
            trade_id=trade_id,
            item_id=item_id,
            from_user_id=offer["creator_id"],
            to_user_id=user["id"],
        )

    await repos.offers.update_status(offer_id, "completed")

    await callback.message.edit_text(
        f"✅ Сделка #{trade_id} создана!\n\n"
        f"Предложение: {offer['title']}\n"
        f"Продавец: @{offer.get('username') or '-'}\n"
        f"Статус: pending (ожидает подтверждения)\n\n"
        f"Обе стороны должны подтвердить обмен.",
        reply_markup=back_to_main_keyboard(),
    )
    await callback.answer(f"Сделка #{trade_id} создана")


@router.message(Command("confirm_trade"))
async def cmd_confirm_trade(message: Message, repos: Repositories) -> None:
    user = await repos.users.get_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден")
        return

    # Находим pending сделки пользователя
    trades = await repos.trades.get_by_user(user["id"])
    pending = [t for t in trades if t["status"] == "pending"]

    if not pending:
        await message.answer(
            "❌ У вас нет сделок, ожидающих подтверждения",
            reply_markup=back_to_main_keyboard(),
        )
        return

    text = "🔄 <b>Сделки, ожидающие подтверждения</b>\n\n"
    for trade in pending:
        text += (
            f"• Сделка #{trade['id']}\n"
            f"  Статус: {trade['status']}\n"
            f"  Чтобы подтвердить: /confirm_trade_{trade['id']}\n\n"
        )

    await message.answer(text, reply_markup=back_to_main_keyboard())