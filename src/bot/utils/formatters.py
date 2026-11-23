"""Утилиты форматирования сообщений."""

from bot.utils.prices import AggregatedPrice


def format_user_profile(user: dict) -> str:
    steam_status = "✅ Привязан" if user.get("is_steam_linked") else "❌ Не привязан"
    ban_status = "🔴 Забанен" if user.get("is_banned") else "🟢 Активен"
    return (
        f"👤 <b>Профиль</b>\n\n"
        f"ID: <code>{user['telegram_id']}</code>\n"
        f"Имя: {user.get('first_name') or '-'} {user.get('last_name') or '-'}\n"
        f"Username: @{user.get('username') or '-'}\n"
        f"Steam: {steam_status}\n"
        f"Статус: {ban_status}\n"
        f"Рейтинг: {user.get('rating', 0):.1f} ⭐\n"
        f"Сделок: {user.get('trades_count', 0)}\n"
    )


def format_item(item: dict) -> str:
    return (
        f"🎁 <b>{item.get('market_hash_name', 'Неизвестный предмет')}</b>\n"
        f"Тип: {item.get('item_type') or '-'}\n"
        f"Редкость: {item.get('rarity') or '-'}\n"
        f"Качество: {item.get('quality') or '-'}\n"
        f"Float: {item.get('float_value') or '-'}\n"
        f"Цена Steam: ${item.get('price_steam') or 0:.2f}\n"
        f"Торгуемый: {'Да' if item.get('is_tradable') else 'Нет'}\n"
    )


def format_item_with_price(item: dict, price: AggregatedPrice | None = None) -> str:
    """Форматирование предмета с ценой."""
    name = item.get('market_hash_name', 'Неизвестный предмет')
    quality = item.get('quality') or '-'
    float_val = item.get('float_value') or '-'
    
    price_str = "—"
    if price and price.best_price_usd:
        price_str = f"${price.best_price_usd:.2f}"
    elif item.get('price_steam'):
        price_str = f"${item['price_steam']:.2f}"
    
    return (
        f"  <code>{item['id']}</code>. {name}\n"
        f"     Качество: {quality} | Float: {float_val} | Цена: {price_str}\n"
    )


def format_offer(offer: dict) -> str:
    return (
        f"📋 <b>{offer['title']}</b>\n"
        f"Продавец: @{offer.get('username') or '-'}\n"
        f"Рейтинг: {offer.get('rating', 0):.1f} ⭐\n"
        f"Цена: ${offer.get('price', 0):.2f}\n"
        f"Статус: {offer['status']}\n"
    )