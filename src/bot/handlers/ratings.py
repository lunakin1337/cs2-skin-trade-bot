"""Рейтинг, отзывы и оценки по завершённым сделкам."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import back_to_main_keyboard, rating_keyboard
from bot.utils.formatters import trade_role
from bot.utils.telegram import edit_or_send, notify
from bot.utils.users import ensure_user
from database.repository import Repositories

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("rating"))
async def cmd_rating(message: Message, repos: Repositories) -> None:
    await ensure_user(repos, message.from_user)
    user = await repos.users.get_by_telegram_id(message.from_user.id)

    ratings = await repos.ratings.get_for_user(user["id"])
    average = await repos.ratings.get_average_rating(user["id"])

    if not ratings:
        await message.answer(
            f"⭐ <b>Ваш рейтинг</b>\n\n"
            f"Средний рейтинг: {average:.1f} ⭐\n"
            "Отзывов пока нет — они появляются после завершённых сделок.",
            reply_markup=back_to_main_keyboard(),
        )
        return

    lines = [
        "⭐ <b>Ваш рейтинг</b>",
        "",
        f"Средний рейтинг: {average:.1f} ⭐ · отзывов: {len(ratings)}",
        "",
        "<b>Последние отзывы:</b>",
    ]
    for rating in ratings[:5]:
        lines.append(
            f"• {rating['score']} ⭐ от @{rating.get('from_username') or '—'}\n"
            f"   {rating.get('comment') or '—'}"
        )

    await message.answer("\n".join(lines), reply_markup=back_to_main_keyboard())


@router.callback_query(F.data.startswith("rate_menu_"))
async def cb_rate_menu(callback: CallbackQuery, repos: Repositories) -> None:
    trade_id = _int_tail(callback.data)
    trade = await repos.trades.get_by_id(trade_id) if trade_id else None
    if not trade:
        await notify(callback, "Сделка не найдена", alert=True)
        return

    user = await ensure_user(repos, callback.from_user)
    if trade["buyer_id"] != user["id"] and trade["seller_id"] != user["id"]:
        await notify(callback, "Это не ваша сделка", alert=True)
        return
    if trade["status"] != "completed":
        await notify(callback, "Оценить можно только завершённую сделку", alert=True)
        return
    if await repos.ratings.exists(trade_id, user["id"]):
        await notify(callback, "Вы уже оценили эту сделку", alert=True)
        return

    role = trade_role(trade, user["id"])
    counterpart = (trade.get("seller_username") if role == "buyer" else trade.get("buyer_username")) or "—"

    await edit_or_send(
        callback.message,
        f"⭐ <b>Оценка по сделке #{trade_id}</b>\n\n"
        f"Контрагент: @{counterpart}\n"
        "Насколько всё прошло гладко?",
        rating_keyboard(trade_id),
    )
    await notify(callback)


@router.callback_query(F.data.regexp(r"^rate_\d+_[1-5]$"))
async def cb_rate(callback: CallbackQuery, repos: Repositories) -> None:
    _, raw_trade_id, raw_score = callback.data.split("_")
    trade_id, score = int(raw_trade_id), int(raw_score)

    trade = await repos.trades.get_by_id(trade_id)
    if not trade or trade["status"] != "completed":
        await notify(callback, "Оценка доступна только по завершённой сделке", alert=True)
        return

    user = await ensure_user(repos, callback.from_user)
    if trade["buyer_id"] != user["id"] and trade["seller_id"] != user["id"]:
        await notify(callback, "Это не ваша сделка", alert=True)
        return
    if await repos.ratings.exists(trade_id, user["id"]):
        await notify(callback, "Вы уже оценили эту сделку", alert=True)
        return

    target_id = trade["seller_id"] if trade["buyer_id"] == user["id"] else trade["buyer_id"]
    await repos.ratings.create(
        trade_id=trade_id,
        from_user_id=user["id"],
        to_user_id=target_id,
        score=score,
    )
    new_rating = await repos.users.recompute_rating(target_id)

    await edit_or_send(
        callback.message,
        f"Спасибо! Оценка {score} ⭐ по сделке #{trade_id} сохранена.\n"
        "Посмотреть свои отзывы можно в /rating.",
        back_to_main_keyboard(),
    )
    await notify(callback, "Оценка сохранена")

    target = await repos.users.get_by_id(target_id)
    if target:
        try:
            await callback.bot.send_message(
                target["telegram_id"],
                f"⭐ Вам поставили {score} ⭐ по сделке #{trade_id}.\n"
                f"Текущий рейтинг: {new_rating:.1f} ⭐",
            )
        except Exception as error:  # пользователь мог заблокировать бота
            logger.debug("Не удалось уведомить пользователя %s: %s", target_id, error)


def _int_tail(callback_data: str) -> int | None:
    try:
        return int(callback_data.rsplit("_", 1)[-1])
    except ValueError:
        return None
