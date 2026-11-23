"""Админ-панель."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from database.repository import Repositories
from bot.keyboards.inline import back_to_main_keyboard

router = Router()


@router.message(Command("admin"))
async def cmd_admin(message: Message, repos: Repositories, config) -> None:
    admin_ids = config.admin_ids

    if message.from_user.id not in admin_ids:
        await message.answer("❌ У вас нет прав доступа к админ-панели.")
        return

    # Статистика
    users_count = await repos.db.execute("SELECT COUNT(*) as cnt FROM users")
    users_row = await users_count.fetchone()

    trades_count = await repos.db.execute("SELECT COUNT(*) as cnt FROM trades")
    trades_row = await trades_count.fetchone()

    offers_count = await repos.db.execute(
        "SELECT COUNT(*) as cnt FROM offers WHERE status = 'active'"
    )
    offers_row = await offers_count.fetchone()

    disputes_count = await repos.db.execute(
        "SELECT COUNT(*) as cnt FROM disputes WHERE status = 'open'"
    )
    disputes_row = await disputes_count.fetchone()

    await message.answer(
        f"🛠 <b>Админ-панель</b>\n\n"
        f"👥 Пользователей: {users_row['cnt'] if users_row else 0}\n"
        f"🔄 Сделок: {trades_row['cnt'] if trades_row else 0}\n"
        f"📋 Активных предложений: {offers_row['cnt'] if offers_row else 0}\n"
        f"⚖️ Открытых споров: {disputes_row['cnt'] if disputes_row else 0}\n\n"
        f"Команды:\n"
        f"/users — список пользователей\n"
        f"/ban <user_id> — забанить\n"
        f"/unban <user_id> — разбанить\n"
        f"/disputes — список споров\n"
        f"/resolve <dispute_id> <причина> — решить спор",
        reply_markup=back_to_main_keyboard(),
    )


@router.message(Command("users"))
async def cmd_admin_users(message: Message, repos: Repositories, config) -> None:
    if message.from_user.id not in config.admin_ids:
        return

    cur = await repos.db.execute(
        "SELECT id, telegram_id, username, first_name, is_steam_linked, is_banned, rating, trades_count FROM users ORDER BY id DESC LIMIT 20"
    )
    rows = await cur.fetchall()

    text = "👥 <b>Пользователи (последние 20)</b>\n\n"
    for row in rows:
        text += (
            f"• ID: {row['id']} | TG: {row['telegram_id']}\n"
            f"  @{row['username'] or '-'} | {row['first_name'] or '-'}\n"
            f"  Steam: {'✅' if row['is_steam_linked'] else '❌'} | "
            f"Ban: {'🔴' if row['is_banned'] else '🟢'} | "
            f"Rating: {row['rating']:.1f} | Trades: {row['trades_count']}\n\n"
        )

    await message.answer(text, reply_markup=back_to_main_keyboard())


@router.message(Command("ban"))
async def cmd_admin_ban(message: Message, repos: Repositories, config) -> None:
    if message.from_user.id not in config.admin_ids:
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /ban <user_id>")
        return

    try:
        user_id = int(args[1])
    except ValueError:
        await message.answer("Неверный ID")
        return

    await repos.users.ban(user_id)
    await message.answer(f"✅ Пользователь {user_id} забанен")


@router.message(Command("unban"))
async def cmd_admin_unban(message: Message, repos: Repositories, config) -> None:
    if message.from_user.id not in config.admin_ids:
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /unban <user_id>")
        return

    try:
        user_id = int(args[1])
    except ValueError:
        await message.answer("Неверный ID")
        return

    await repos.users.unban(user_id)
    await message.answer(f"✅ Пользователь {user_id} разбанен")


@router.message(Command("disputes"))
async def cmd_admin_disputes(message: Message, repos: Repositories, config) -> None:
    if message.from_user.id not in config.admin_ids:
        return

    disputes = await repos.disputes.get_open()

    if not disputes:
        await message.answer("Открытых споров нет", reply_markup=back_to_main_keyboard())
        return

    text = "⚖️ <b>Открытые споры</b>\n\n"
    for d in disputes:
        text += (
            f"• Спор #{d['id']} | Сделка #{d['trade_id']}\n"
            f"  Открыл: @{d.get('opened_by_username') or '-'}\n"
            f"  Причина: {d['reason']}\n\n"
        )

    await message.answer(text, reply_markup=back_to_main_keyboard())


@router.message(Command("resolve"))
async def cmd_admin_resolve(message: Message, repos: Repositories, config) -> None:
    if message.from_user.id not in config.admin_ids:
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Использование: /resolve <dispute_id> <причина>")
        return

    try:
        dispute_id = int(args[1])
    except ValueError:
        await message.answer("Неверный ID спора")
        return

    reason = args[2]
    await repos.disputes.resolve(dispute_id, reason)
    await message.answer(f"✅ Спор #{dispute_id} решён")