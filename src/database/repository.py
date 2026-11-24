"""Repository pattern для доступа к данным."""

import aiosqlite
import json
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone


class Database:
    """Обёртка над aiosqlite для работы с БД."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def execute(self, query: str, params: tuple = ()) -> aiosqlite.Cursor:
        if not self._connection:
            raise RuntimeError("Database not connected")
        return await self._connection.execute(query, params)

    async def commit(self) -> None:
        if self._connection:
            await self._connection.commit()

    async def init_schema(self, schema_sql: str) -> None:
        if not self._connection:
            raise RuntimeError("Database not connected")
        await self._connection.executescript(schema_sql)
        await self._connection.commit()


class UserRepository:
    def __init__(self, db: Database):
        self.db = db

    async def create_or_update(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        cur = await self.db.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = await cur.fetchone()

        if row:
            await self.db.execute(
                """
                UPDATE users
                SET username = ?, first_name = ?, last_name = ?, updated_at = datetime('now')
                WHERE telegram_id = ?
                """,
                (username, first_name, last_name, telegram_id),
            )
        else:
            await self.db.execute(
                """
                INSERT INTO users (telegram_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
                """,
                (telegram_id, username, first_name, last_name),
            )
        await self.db.commit()

        return await self.get_by_telegram_id(telegram_id)

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def link_steam(
        self,
        user_id: int,
        steam_id: str,
        steam_trade_url: str,
        *,
        trade_partner: Optional[str] = None,
        trade_token: Optional[str] = None,
        persona_name: Optional[str] = None,
        avatar_url: Optional[str] = None,
        profile_url: Optional[str] = None,
    ) -> None:
        """Привязать Steam-аккаунт и trade URL одним обновлением."""
        await self.db.execute(
            """
            UPDATE users
            SET steam_id = ?,
                steam_trade_url = ?,
                steam_trade_partner = ?,
                steam_trade_token = ?,
                is_steam_linked = 1,
                steam_linked_at = datetime('now'),
                steam_persona = COALESCE(?, steam_persona),
                steam_avatar_url = COALESCE(?, steam_avatar_url),
                steam_profile_url = COALESCE(?, steam_profile_url),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                steam_id,
                steam_trade_url,
                trade_partner,
                trade_token,
                persona_name,
                avatar_url,
                profile_url,
                user_id,
            ),
        )
        await self.db.commit()

    async def set_steam_profile(
        self,
        user_id: int,
        persona_name: Optional[str],
        avatar_url: Optional[str],
        profile_url: Optional[str],
    ) -> None:
        """Обновить кэш публичного профиля Steam."""
        await self.db.execute(
            """
            UPDATE users
            SET steam_persona = ?, steam_avatar_url = ?, steam_profile_url = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (persona_name, avatar_url, profile_url, user_id),
        )
        await self.db.commit()

    async def set_trade_url(
        self,
        user_id: int,
        steam_trade_url: str,
        trade_partner: str,
        trade_token: str,
    ) -> None:
        """Обновить только trade URL (например, если протух токен)."""
        await self.db.execute(
            """
            UPDATE users
            SET steam_trade_url = ?, steam_trade_partner = ?, steam_trade_token = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (steam_trade_url, trade_partner, trade_token, user_id),
        )
        await self.db.commit()

    async def touch_inventory_sync(self, user_id: int) -> None:
        """Отметить время успешной синхронизации инвентаря."""
        await self.db.execute(
            "UPDATE users SET inventory_synced_at = datetime('now') WHERE id = ?",
            (user_id,),
        )
        await self.db.commit()

    async def increment_trades_count(self, user_id: int) -> None:
        """Посчитать завершённую сделку пользователю."""
        await self.db.execute(
            "UPDATE users SET trades_count = trades_count + 1, updated_at = datetime('now') WHERE id = ?",
            (user_id,),
        )
        await self.db.commit()

    async def recompute_rating(self, user_id: int) -> float:
        """Пересчитать средний рейтинг по отзывам."""
        await self.db.execute(
            """
            UPDATE users
            SET rating = COALESCE((SELECT AVG(score) FROM ratings WHERE to_user_id = ?), 0),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (user_id, user_id),
        )
        await self.db.commit()

        user = await self.get_by_id(user_id)
        return float(user["rating"]) if user else 0.0

    async def ban(self, user_id: int) -> None:
        await self.db.execute(
            "UPDATE users SET is_banned = 1, updated_at = datetime('now') WHERE id = ?",
            (user_id,),
        )
        await self.db.commit()

    async def unban(self, user_id: int) -> None:
        await self.db.execute(
            "UPDATE users SET is_banned = 0, updated_at = datetime('now') WHERE id = ?",
            (user_id,),
        )
        await self.db.commit()


ITEM_FIELDS = (
    "steam_asset_id",
    "market_hash_name",
    "item_name",
    "item_type",
    "rarity",
    "quality",
    "exterior",
    "float_value",
    "paint_seed",
    "stickers",
    "image_url",
    "icon_url",
    "class_id",
    "instance_id",
    "price_steam",
    "price_csfloat",
    "price_buff",
    "is_tradable",
    "is_marketable",
)

FLAG_FIELDS = {"is_tradable", "is_marketable"}


class ItemRepository:
    def __init__(self, db: Database):
        self.db = db

    async def add(self, owner_id: int, steam_asset_id: str, market_hash_name: str, **fields: Any) -> int:
        """Добавить предмет вручную (данные инвентаря обычно приходят через sync)."""
        item = {"steam_asset_id": steam_asset_id, "market_hash_name": market_hash_name}
        item.update({key: value for key, value in fields.items() if key in ITEM_FIELDS})
        columns = ["owner_id", *item.keys()]
        placeholders = ", ".join("?" for _ in columns)
        cur = await self.db.execute(
            f"INSERT INTO items ({', '.join(columns)}) VALUES ({placeholders})",
            (owner_id, *(_normalize_item_value(key, value) for key, value in item.items())),
        )
        await self.db.commit()
        return cur.lastrowid

    async def sync(self, owner_id: int, items: List[Dict[str, Any]]) -> tuple[int, int, int]:
        """Привести инвентарь пользователя к состоянию Steam.

        Возвращает (добавлено, обновлено, удалено).
        """
        cur = await self.db.execute(
            "SELECT id, steam_asset_id FROM items WHERE owner_id = ?",
            (owner_id,),
        )
        existing = {row["steam_asset_id"]: row["id"] for row in await cur.fetchall()}

        created = updated = 0
        seen: set[str] = set()

        for item in items:
            asset_id = str(item.get("steam_asset_id") or "").strip()
            if not asset_id:
                continue
            seen.add(asset_id)
            values = {key: item[key] for key in ITEM_FIELDS if key in item}

            if asset_id in existing:
                assignments = ", ".join(f"{key} = ?" for key in values)
                await self.db.execute(
                    f"""
                    UPDATE items
                    SET {assignments}, synced_at = datetime('now'), updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (
                        *(_normalize_item_value(key, value) for key, value in values.items()),
                        existing[asset_id],
                    ),
                )
                updated += 1
            else:
                columns = ["owner_id", *values.keys(), "synced_at"]
                placeholders = ", ".join("?" for _ in columns)
                await self.db.execute(
                    f"""
                    INSERT INTO items ({', '.join(columns)}, updated_at)
                    VALUES ({placeholders}, datetime('now'))
                    """,
                    (
                        owner_id,
                        *(_normalize_item_value(key, value) for key, value in values.items()),
                        _now(),
                    ),
                )
                created += 1

        removed_ids = [item_id for asset_id, item_id in existing.items() if asset_id not in seen]
        if removed_ids:
            placeholders = ", ".join("?" for _ in removed_ids)
            await self.db.execute(f"DELETE FROM items WHERE id IN ({placeholders})", tuple(removed_ids))

        await self.db.commit()
        return created, updated, len(removed_ids)

    async def get_by_owner(
        self,
        owner_id: int,
        tradable_only: bool = False,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM items WHERE owner_id = ?"
        params: list[Any] = [owner_id]
        if tradable_only:
            query += " AND is_tradable = 1"
        query += " ORDER BY COALESCE(price_steam, 0) DESC, market_hash_name ASC"
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        cur = await self.db.execute(query, tuple(params))
        return [dict(row) for row in await cur.fetchall()]

    async def count_by_owner(self, owner_id: int, tradable_only: bool = False) -> int:
        query = "SELECT COUNT(*) AS cnt FROM items WHERE owner_id = ?"
        if tradable_only:
            query += " AND is_tradable = 1"
        cur = await self.db.execute(query, (owner_id,))
        row = await cur.fetchone()
        return row["cnt"] if row else 0

    async def sum_price(self, owner_id: int) -> float:
        """Сумма известных цен Steam по инвентарю пользователя."""
        cur = await self.db.execute(
            "SELECT COALESCE(SUM(price_steam), 0) AS total FROM items WHERE owner_id = ?",
            (owner_id,),
        )
        row = await cur.fetchone()
        return float(row["total"]) if row else 0.0

    async def get_by_id(self, item_id: int) -> Optional[Dict[str, Any]]:
        cur = await self.db.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_by_ids(self, item_ids: List[int]) -> List[Dict[str, Any]]:
        """Предметы по списку id (для карточек предложений)."""
        if not item_ids:
            return []
        placeholders = ", ".join("?" for _ in item_ids)
        cur = await self.db.execute(
            f"SELECT * FROM items WHERE id IN ({placeholders}) ORDER BY COALESCE(price_steam, 0) DESC",
            tuple(item_ids),
        )
        return [dict(row) for row in await cur.fetchall()]

    async def rarity_map(self, names: List[str]) -> Dict[str, str]:
        """Редкость по имени скина — из инвентарей, где Steam её уже отдал."""
        unique = [name for name in dict.fromkeys(names) if name]
        if not unique:
            return {}
        placeholders = ", ".join("?" for _ in unique)
        cur = await self.db.execute(
            f"""
            SELECT market_hash_name, MAX(rarity) AS rarity
            FROM items
            WHERE rarity IS NOT NULL AND market_hash_name IN ({placeholders})
            GROUP BY market_hash_name
            """,
            tuple(unique),
        )
        return {row["market_hash_name"]: row["rarity"] for row in await cur.fetchall()}

    async def apply_prices(self, owner_id: int, prices: Dict[str, float]) -> None:
        """Записать цены Steam для всех предметов пользователя с этими именами."""
        for market_hash_name, price in prices.items():
            await self.db.execute(
                """
                UPDATE items
                SET price_steam = ?, updated_at = datetime('now')
                WHERE owner_id = ? AND market_hash_name = ?
                """,
                (price, owner_id, market_hash_name),
            )
        await self.db.commit()

    async def delete(self, item_id: int) -> None:
        await self.db.execute("DELETE FROM items WHERE id = ?", (item_id,))
        await self.db.commit()

    async def set_tradable(self, item_id: int, tradable: bool) -> None:
        await self.db.execute(
            "UPDATE items SET is_tradable = ?, updated_at = datetime('now') WHERE id = ?",
            (int(tradable), item_id),
        )
        await self.db.commit()


def _normalize_item_value(key: str, value: Any) -> Any:
    if key in FLAG_FIELDS:
        return int(bool(value))
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class OfferRepository:
    def __init__(self, db: Database):
        self.db = db

    async def create(
        self,
        creator_id: int,
        title: str,
        items_offered: List[int],
        items_wanted: str,
        description: Optional[str] = None,
        price: float = 0.0,
        wanted_name: Optional[str] = None,
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO offers (
                creator_id, title, description, items_offered, items_wanted, price, wanted_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                creator_id,
                title,
                description,
                json.dumps(items_offered),
                items_wanted,
                price,
                wanted_name,
            ),
        )
        await self.db.commit()
        return cur.lastrowid

    async def get_active(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        cur = await self.db.execute(
            """
            SELECT o.*, u.username, u.first_name, u.telegram_id, u.rating
            FROM offers o
            JOIN users u ON o.creator_id = u.id
            WHERE o.status = 'active'
            ORDER BY o.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_by_id(self, offer_id: int) -> Optional[Dict[str, Any]]:
        cur = await self.db.execute(
            """
            SELECT o.*, u.username, u.first_name, u.telegram_id, u.rating
            FROM offers o
            JOIN users u ON o.creator_id = u.id
            WHERE o.id = ?
            """,
            (offer_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def count_active(self) -> int:
        cur = await self.db.execute("SELECT COUNT(*) AS cnt FROM offers WHERE status = 'active'")
        row = await cur.fetchone()
        return row["cnt"] if row else 0

    async def get_by_creator(self, creator_id: int) -> List[Dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM offers WHERE creator_id = ? ORDER BY created_at DESC",
            (creator_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def delete(self, offer_id: int) -> None:
        await self.db.execute("DELETE FROM offers WHERE id = ?", (offer_id,))
        await self.db.commit()

    async def update_status(self, offer_id: int, status: str) -> None:
        await self.db.execute(
            "UPDATE offers SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, offer_id),
        )
        await self.db.commit()


TRADE_SELECT = """
    SELECT t.*,
           b.username AS buyer_username,
           s.username AS seller_username,
           b.steam_trade_url AS buyer_trade_url,
           s.steam_trade_url AS seller_trade_url,
           b.rating AS buyer_rating,
           s.rating AS seller_rating
    FROM trades t
    JOIN users b ON t.buyer_id = b.id
    JOIN users s ON t.seller_id = s.id
"""


class TradeRepository:
    def __init__(self, db: Database):
        self.db = db

    async def create(
        self,
        buyer_id: int,
        seller_id: int,
        offer_id: Optional[int] = None,
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO trades (buyer_id, seller_id, offer_id, status)
            VALUES (?, ?, ?, 'pending')
            """,
            (buyer_id, seller_id, offer_id),
        )
        await self.db.commit()
        return cur.lastrowid

    async def get_by_id(self, trade_id: int) -> Optional[Dict[str, Any]]:
        cur = await self.db.execute(f"{TRADE_SELECT} WHERE t.id = ?", (trade_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_by_user(self, user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        cur = await self.db.execute(
            f"{TRADE_SELECT} WHERE t.buyer_id = ? OR t.seller_id = ? "
            "ORDER BY t.created_at DESC LIMIT ?",
            (user_id, user_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def set_confirmed(self, trade_id: int, role: str, confirmed: bool = True) -> None:
        """Отметить подтверждение одной из сторон (buyer/seller)."""
        column = "buyer_confirmed_at" if role == "buyer" else "seller_confirmed_at"
        value = "datetime('now')" if confirmed else "NULL"
        await self.db.execute(
            f"UPDATE trades SET {column} = {value}, updated_at = datetime('now') WHERE id = ?",
            (trade_id,),
        )
        await self.db.commit()

    async def set_completed_side(self, trade_id: int, role: str) -> None:
        """Отметить, что сторона получила скины."""
        column = "buyer_completed_at" if role == "buyer" else "seller_completed_at"
        await self.db.execute(
            f"UPDATE trades SET {column} = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (trade_id,),
        )
        await self.db.commit()

    async def mark_completed(self, trade_id: int) -> None:
        await self.db.execute(
            """
            UPDATE trades
            SET status = 'completed', completed_at = datetime('now'), updated_at = datetime('now')
            WHERE id = ?
            """,
            (trade_id,),
        )
        await self.db.commit()

    async def set_holding(self, trade_id: int, hold_days: int) -> None:
        """Оба отметили получение: сделка ждёт окончания Trade Protection.

        Срок считается от последнего «Получил»: до finalize_at отправитель ещё может
        отменить трейд в Steam, поэтому закрывать сделку раньше нельзя.
        """
        await self.db.execute(
            """
            UPDATE trades
            SET status = 'holding',
                finalize_at = datetime(MAX(buyer_completed_at, seller_completed_at), ?),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (f"+{int(hold_days)} days", trade_id),
        )
        await self.db.commit()

    async def finalize(self, trade_id: int) -> bool:
        """Ленивый переход holding → completed, если срок защиты истёк.

        Возвращает True только тому вызову, который реально закрыл сделку:
        условие в UPDATE не даёт начислить счётчики дважды при двух чтениях подряд.
        """
        cur = await self.db.execute(
            """
            UPDATE trades
            SET status = 'completed',
                completed_at = finalize_at,
                updated_at = datetime('now')
            WHERE id = ? AND status = 'holding'
              AND finalize_at IS NOT NULL AND finalize_at <= datetime('now')
            """,
            (trade_id,),
        )
        await self.db.commit()
        return cur.rowcount == 1

    async def update_status(self, trade_id: int, status: str) -> None:
        await self.db.execute(
            "UPDATE trades SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, trade_id),
        )
        await self.db.commit()

    async def set_steam_trade_offer_id(self, trade_id: int, steam_offer_id: str) -> None:
        await self.db.execute(
            "UPDATE trades SET steam_trade_offer_id = ? WHERE id = ?",
            (steam_offer_id, trade_id),
        )
        await self.db.commit()


class TradeItemRepository:
    def __init__(self, db: Database):
        self.db = db

    async def add(
        self,
        trade_id: int,
        item_id: int,
        from_user_id: int,
        to_user_id: int,
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO trade_items (trade_id, item_id, from_user_id, to_user_id)
            VALUES (?, ?, ?, ?)
            """,
            (trade_id, item_id, from_user_id, to_user_id),
        )
        await self.db.commit()
        return cur.lastrowid

    async def get_by_trade(self, trade_id: int) -> List[Dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM trade_items WHERE trade_id = ?",
            (trade_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


class RatingRepository:
    def __init__(self, db: Database):
        self.db = db

    async def create(
        self,
        trade_id: int,
        from_user_id: int,
        to_user_id: int,
        score: int,
        comment: Optional[str] = None,
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO ratings (trade_id, from_user_id, to_user_id, score, comment)
            VALUES (?, ?, ?, ?, ?)
            """,
            (trade_id, from_user_id, to_user_id, score, comment),
        )
        await self.db.commit()
        return cur.lastrowid

    async def exists(self, trade_id: int, from_user_id: int) -> bool:
        cur = await self.db.execute(
            "SELECT 1 FROM ratings WHERE trade_id = ? AND from_user_id = ?",
            (trade_id, from_user_id),
        )
        return await cur.fetchone() is not None

    async def get_for_user(self, user_id: int) -> List[Dict[str, Any]]:
        cur = await self.db.execute(
            """
            SELECT r.*, u.username as from_username
            FROM ratings r
            JOIN users u ON r.from_user_id = u.id
            WHERE r.to_user_id = ?
            ORDER BY r.created_at DESC
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_average_rating(self, user_id: int) -> float:
        cur = await self.db.execute(
            "SELECT AVG(score) as avg_score FROM ratings WHERE to_user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return float(row["avg_score"]) if row and row["avg_score"] else 0.0


class DisputeRepository:
    def __init__(self, db: Database):
        self.db = db

    async def create(
        self,
        trade_id: int,
        opened_by: int,
        reason: str,
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO disputes (trade_id, opened_by, reason, status)
            VALUES (?, ?, ?, 'open')
            """,
            (trade_id, opened_by, reason),
        )
        await self.db.commit()
        return cur.lastrowid

    async def get_open(self) -> List[Dict[str, Any]]:
        cur = await self.db.execute(
            """
            SELECT d.*, u.username as opened_by_username
            FROM disputes d
            JOIN users u ON d.opened_by = u.id
            WHERE d.status = 'open'
            ORDER BY d.created_at DESC
            """
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_open_by_trade(self, trade_id: int) -> Optional[Dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM disputes WHERE trade_id = ? AND status = 'open'",
            (trade_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def resolve(self, dispute_id: int, admin_note: str) -> None:
        await self.db.execute(
            """
            UPDATE disputes
            SET status = 'resolved', admin_note = ?, resolved_at = datetime('now')
            WHERE id = ?
            """,
            (admin_note, dispute_id),
        )
        await self.db.commit()


class SettingsRepository:
    def __init__(self, db: Database):
        self.db = db

    async def get(self, key: str) -> Optional[str]:
        cur = await self.db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else None

    async def set(self, key: str, value: str) -> None:
        await self.db.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
            """,
            (key, value),
        )
        await self.db.commit()


class SkinRepository:
    """Текстовая база всех скинов CS2 (каталог для «хочу»)."""

    def __init__(self, db: Database):
        self.db = db

    async def upsert_many(self, skins: List[Dict[str, Any]]) -> int:
        """Записать/обновить каталог пачкой, вернуть количество строк."""
        for skin in skins:
            name = (skin.get("market_hash_name") or "").strip()
            if not name:
                continue
            await self.db.execute(
                """
                INSERT INTO skins (
                    market_hash_name, name, price_text, price_value, icon_url,
                    category, weapon, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(market_hash_name) DO UPDATE SET
                    name = excluded.name,
                    price_text = COALESCE(excluded.price_text, skins.price_text),
                    price_value = COALESCE(excluded.price_value, skins.price_value),
                    icon_url = COALESCE(excluded.icon_url, skins.icon_url),
                    category = COALESCE(excluded.category, skins.category),
                    weapon = COALESCE(excluded.weapon, skins.weapon),
                    updated_at = datetime('now')
                """,
                (
                    name,
                    skin.get("name") or name,
                    skin.get("price_text"),
                    skin.get("price_value"),
                    skin.get("icon_url"),
                    skin.get("category"),
                    skin.get("weapon"),
                ),
            )
        await self.db.commit()
        return len(skins)

    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Поиск по словам: «AWP Asiimov» находит «AWP | Asiimov (Field-Tested)»."""
        tokens = [token for token in re.split(r"\s+", query.strip()) if token][:5]
        if not tokens:
            return []

        condition = " AND ".join("market_hash_name LIKE ?" for _ in tokens)
        params = [f"%{token}%" for token in tokens]
        cur = await self.db.execute(
            f"""
            SELECT * FROM skins
            WHERE {condition}
            ORDER BY LENGTH(market_hash_name), market_hash_name
            LIMIT ?
            """,
            (*params, limit),
        )
        return [dict(row) for row in await cur.fetchall()]

    async def search_structured(
        self,
        tokens: List[str],
        wear: Optional[str] = None,
        max_price: Optional[float] = None,
        stattrak: bool = False,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Поиск по разобранному запросу: токены, износ, цена, StatTrak."""
        conditions: List[str] = []
        params: List[Any] = []

        for token in tokens:
            conditions.append("market_hash_name LIKE ?")
            params.append(f"%{token}%")

        if stattrak:
            conditions.append("market_hash_name LIKE 'StatTrak%'")

        if wear:
            conditions.append("market_hash_name LIKE ?")
            params.append(f"%({wear})%")

        if max_price:
            conditions.append("(price_value IS NULL OR price_value <= ?)")
            params.append(max_price)

        where = " AND ".join(conditions) if conditions else "1 = 1"
        cur = await self.db.execute(
            f"""
            SELECT * FROM skins
            WHERE {where}
            ORDER BY COALESCE(price_value, 1000000), LENGTH(market_hash_name)
            LIMIT ?
            """,
            (*params, limit),
        )
        return [dict(row) for row in await cur.fetchall()]

    async def all_names(self, limit: int = 5000) -> List[str]:
        cur = await self.db.execute(
            "SELECT market_hash_name FROM skins ORDER BY LENGTH(market_hash_name) LIMIT ?",
            (limit,),
        )
        return [row["market_hash_name"] for row in await cur.fetchall()]

    async def category_tree(self) -> List[Dict[str, Any]]:
        """Категории с количеством позиций и оружием внутри."""
        cur = await self.db.execute(
            """
            SELECT category, COUNT(*) AS cnt
            FROM skins
            GROUP BY category
            ORDER BY cnt DESC
            """
        )
        categories = [dict(row) for row in await cur.fetchall()]

        cur = await self.db.execute(
            """
            SELECT category, weapon, COUNT(*) AS cnt
            FROM skins
            WHERE weapon IS NOT NULL
            GROUP BY category, weapon
            ORDER BY cnt DESC
            """
        )
        weapons: Dict[str, List[Dict[str, Any]]] = {}
        for row in await cur.fetchall():
            weapons.setdefault(row["category"], []).append(
                {"weapon": row["weapon"], "count": row["cnt"]}
            )

        for category in categories:
            category["weapons"] = weapons.get(category["category"], [])
        return categories

    def _filters(
        self,
        category: Optional[str],
        weapon: Optional[str],
        query: Optional[str],
    ) -> tuple[str, List[Any]]:
        conditions: List[str] = []
        params: List[Any] = []

        if category:
            conditions.append("category = ?")
            params.append(category)
        if weapon:
            conditions.append("weapon = ?")
            params.append(weapon)
        if query:
            conditions.append("market_hash_name LIKE ?")
            params.append(f"%{query}%")

        where = " AND ".join(conditions) if conditions else "1 = 1"
        return where, params

    async def list_items(
        self,
        category: Optional[str] = None,
        weapon: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        where, params = self._filters(category, weapon, query)
        cur = await self.db.execute(
            f"""
            SELECT * FROM skins
            WHERE {where}
            ORDER BY COALESCE(price_value, 1000000), market_hash_name
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        )
        return [dict(row) for row in await cur.fetchall()]

    async def count_items(
        self,
        category: Optional[str] = None,
        weapon: Optional[str] = None,
        query: Optional[str] = None,
    ) -> int:
        where, params = self._filters(category, weapon, query)
        cur = await self.db.execute(f"SELECT COUNT(*) AS cnt FROM skins WHERE {where}", tuple(params))
        row = await cur.fetchone()
        return row["cnt"] if row else 0

    async def count(self) -> int:
        cur = await self.db.execute("SELECT COUNT(*) AS cnt FROM skins")
        row = await cur.fetchone()
        return row["cnt"] if row else 0


class Repositories:
    """Контейнер всех репозиториев."""

    def __init__(self, db: Database):
        self.db = db
        self.users = UserRepository(db)
        self.items = ItemRepository(db)
        self.offers = OfferRepository(db)
        self.trades = TradeRepository(db)
        self.trade_items = TradeItemRepository(db)
        self.ratings = RatingRepository(db)
        self.disputes = DisputeRepository(db)
        self.settings = SettingsRepository(db)
        self.skins = SkinRepository(db)