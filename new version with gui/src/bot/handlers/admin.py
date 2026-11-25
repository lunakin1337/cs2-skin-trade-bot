"""Админ-панель и модерация."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards.inline import back_to_main_keyboard
from config.settings import BotConfig
from database.repository import Repositories

router = Router()

DENIED = "❌ У вас нет прав доступа к админ-панели."
USAGE = {
    "ban": "Использование: /ban <telegram_id>",
    "unban": "Использование: /unban <telegram_id>",
    "resolve": "Использование: /resolve <dispute_id> <причина>",
}


async def _require_admin(message: Message, config: BotConfig) -> bool:
    if config.is_admin(message.from_user.id):
        return True
    await message.answer(DENIED)
    return False


def _int_arg(message: Message, index: int = 1) -> int | None:
    parts = (message.text or "").split()
    if len(parts) <= index:
        return None
    try:
        return int(parts[index])
    except ValueError:
        return None


@router.message(Command("admin"))
async def cmd_admin(message: Message, repos: Repositories, config: BotConfig) -> None:
    if not await _require_admin(message, config):
        return

    stats = {}
    for key, query in {
        "users": "SELECT COUNT(*) AS cnt FROM users",
        "trades": "SELECT COUNT(*) AS cnt FROM trades",
        "offers": "SELECT COUNT(*) AS cnt FROM offers WHERE status = 'active'",
        "disputes": "SELECT COUNT(*) AS cnt FROM disputes WHERE status = 'open'",
    }.items():
        cur = await repos.db.execute(query)
        row = await cur.fetchone()
        stats[key] = row["cnt"] if row else 0

    await message.answer(
        "🛠 <b>Админ-панель</b>\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"🔄 Сделок: {stats['trades']}\n"
        f"📋 Активных предложений: {stats['offers']}\n"
        f"⚖️ Открытых споров: {stats['disputes']}\n\n"
        "/users — последние пользователи\n"
        "/ban <telegram_id> — забанить\n"
        "/unban <telegram_id> — разбанить\n"
        "/disputes — открытые споры\n"
        "/resolve <dispute_id> <причина> — решить спор",
        reply_markup=back_to_main_keyboard(),
    )


@router.message(Command("users"))
async def cmd_admin_users(message: Message, repos: Repositories, config: BotConfig) -> None:
    if not await _require_admin(message, config):
        return

    cur = await repos.db.execute(
        """
        SELECT id, telegram_id, username, first_name, is_steam_linked, is_banned, rating, trades_count
        FROM users ORDER BY id DESC LIMIT 20
        """
    )
    rows = await cur.fetchall()

    lines = ["👥 <b>Пользователи (последние 20)</b>", ""]
    for row in rows:
        lines.append(
            f"<code>{row['telegram_id']}</code> @{row['username'] or '—'} · {row['first_name'] or '—'}\n"
            f"   Steam {'✅' if row['is_steam_linked'] else '❌'} · "
            f"{'🔴 бан' if row['is_banned'] else '🟢 активен'} · "
            f"{row['rating']:.1f} ⭐ · {row['trades_count']} сделок"
        )

    await message.answer("\n".join(lines), reply_markup=back_to_main_keyboard())


@router.message(Command("ban"))
async def cmd_admin_ban(message: Message, repos: Repositories, config: BotConfig) -> None:
    if not await _require_admin(message, config):
        return

    telegram_id = _int_arg(message)
    if telegram_id is None:
        await message.answer(USAGE["ban"])
        return

    user = await repos.users.get_by_telegram_id(telegram_id)
    if not user:
        await message.answer("Пользователь не найден")
        return

    await repos.users.ban(user["id"])
    await message.answer(f"✅ Пользователь {telegram_id} забанен")


@router.message(Command("unban"))
async def cmd_admin_unban(message: Message, repos: Repositories, config: BotConfig) -> None:
    if not await _require_admin(message, config):
        return

    telegram_id = _int_arg(message)
    if telegram_id is None:
        await message.answer(USAGE["unban"])
        return

    user = await repos.users.get_by_telegram_id(telegram_id)
    if not user:
        await message.answer("Пользователь не найден")
        return

    await repos.users.unban(user["id"])
    await message.answer(f"✅ Пользователь {telegram_id} разбанен")


@router.message(Command("disputes"))
async def cmd_admin_disputes(message: Message, repos: Repositories, config: BotConfig) -> None:
    if not await _require_admin(message, config):
        return

    disputes = await repos.disputes.get_open()
    if not disputes:
        await message.answer("Открытых споров нет", reply_markup=back_to_main_keyboard())
        return

    lines = ["⚖️ <b>Открытые споры</b>", ""]
    for dispute in disputes:
        lines.append(
            f"<b>#{dispute['id']}</b> · сделка #{dispute['trade_id']} · "
            f"@{dispute.get('opened_by_username') or '—'}\n   {dispute['reason']}"
        )

    await message.answer("\n".join(lines), reply_markup=back_to_main_keyboard())


@router.message(Command("resolve"))
async def cmd_admin_resolve(message: Message, repos: Repositories, config: BotConfig) -> None:
    if not await _require_admin(message, config):
        return

    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(USAGE["resolve"])
        return

    try:
        dispute_id = int(parts[1])
    except ValueError:
        await message.answer("Неверный ID спора")
        return

    await repos.disputes.resolve(dispute_id, parts[2])
    await message.answer(f"✅ Спор #{dispute_id} решён")
