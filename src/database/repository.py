"""Repository pattern для доступа к данным."""

import aiosqlite
import json
from typing import Optional, List, Dict, Any
from datetime import datetime


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
            await self.db.commit()
            return dict(row)
        else:
            cur = await self.db.execute(
                """
                INSERT INTO users (telegram_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
                """,
                (telegram_id, username, first_name, last_name),
            )
            await self.db.commit()
            new_id = cur.lastrowid
            cur2 = await self.db.execute("SELECT * FROM users WHERE id = ?", (new_id,))
            row = await cur2.fetchone()
            return dict(row)

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
    ) -> None:
        await self.db.execute(
            """
            UPDATE users
            SET steam_id = ?, steam_trade_url = ?, is_steam_linked = 1, updated_at = datetime('now')
            WHERE id = ?
            """,
            (steam_id, steam_trade_url, user_id),
        )
        await self.db.commit()

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


class ItemRepository:
    def __init__(self, db: Database):
        self.db = db

    async def add(
        self,
        owner_id: int,
        steam_asset_id: str,
        market_hash_name: str,
        item_name: Optional[str] = None,
        item_type: Optional[str] = None,
        rarity: Optional[str] = None,
        quality: Optional[str] = None,
        exterior: Optional[str] = None,
        float_value: Optional[float] = None,
        paint_seed: Optional[int] = None,
        stickers: Optional[str] = None,
        image_url: Optional[str] = None,
        price_steam: Optional[float] = None,
        price_csfloat: Optional[float] = None,
        price_buff: Optional[float] = None,
        is_tradable: bool = True,
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO items (
                owner_id, steam_asset_id, market_hash_name, item_name, item_type,
                rarity, quality, exterior, float_value, paint_seed, stickers,
                image_url, price_steam, price_csfloat, price_buff, is_tradable
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_id, steam_asset_id, market_hash_name, item_name, item_type,
                rarity, quality, exterior, float_value, paint_seed, stickers,
                image_url, price_steam, price_csfloat, price_buff, int(is_tradable),
            ),
        )
        await self.db.commit()
        return cur.lastrowid

    async def get_by_owner(self, owner_id: int, tradable_only: bool = False) -> List[Dict[str, Any]]:
        if tradable_only:
            cur = await self.db.execute(
                "SELECT * FROM items WHERE owner_id = ? AND is_tradable = 1 ORDER BY created_at DESC",
                (owner_id,),
            )
        else:
            cur = await self.db.execute(
                "SELECT * FROM items WHERE owner_id = ? ORDER BY created_at DESC",
                (owner_id,),
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_by_id(self, item_id: int) -> Optional[Dict[str, Any]]:
        cur = await self.db.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def delete(self, item_id: int) -> None:
        await self.db.execute("DELETE FROM items WHERE id = ?", (item_id,))
        await self.db.commit()

    async def set_tradable(self, item_id: int, tradable: bool) -> None:
        await self.db.execute(
            "UPDATE items SET is_tradable = ?, updated_at = datetime('now') WHERE id = ?",
            (int(tradable), item_id),
        )
        await self.db.commit()


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
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO offers (creator_id, title, description, items_offered, items_wanted, price)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                creator_id,
                title,
                description,
                json.dumps(items_offered),
                items_wanted,
                price,
            ),
        )
        await self.db.commit()
        return cur.lastrowid

    async def get_active(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        cur = await self.db.execute(
            """
            SELECT o.*, u.username, u.first_name, u.rating
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
            SELECT o.*, u.username, u.first_name, u.rating
            FROM offers o
            JOIN users u ON o.creator_id = u.id
            WHERE o.id = ?
            """,
            (offer_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_by_creator(self, creator_id: int) -> List[Dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM offers WHERE creator_id = ? ORDER BY created_at DESC",
            (creator_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def update_status(self, offer_id: int, status: str) -> None:
        await self.db.execute(
            "UPDATE offers SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, offer_id),
        )
        await self.db.commit()


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
        cur = await self.db.execute(
            """
            SELECT t.*, b.username as buyer_username, s.username as seller_username
            FROM trades t
            JOIN users b ON t.buyer_id = b.id
            JOIN users s ON t.seller_id = s.id
            WHERE t.id = ?
            """,
            (trade_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_by_user(self, user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        cur = await self.db.execute(
            """
            SELECT t.*, b.username as buyer_username, s.username as seller_username
            FROM trades t
            JOIN users b ON t.buyer_id = b.id
            JOIN users s ON t.seller_id = s.id
            WHERE t.buyer_id = ? OR t.seller_id = ?
            ORDER BY t.created_at DESC
            LIMIT ?
            """,
            (user_id, user_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

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