from __future__ import annotations

import aiosqlite
from config import DB_PATH


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id              INTEGER PRIMARY KEY,
                phone                    TEXT UNIQUE,
                name                     TEXT,
                language                 TEXT DEFAULT 'uz',
                moysklad_counterparty_id TEXT,
                balance_usd              REAL DEFAULT 0.0,
                balance_updated_at       TIMESTAMP,
                registered_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS orders (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                moysklad_id     TEXT UNIQUE,
                order_number    TEXT,
                telegram_id     INTEGER,
                customer_name   TEXT,
                customer_phone  TEXT,
                total_usd       REAL DEFAULT 0.0,
                balance_usd     REAL DEFAULT 0.0,
                status          TEXT,
                moment          TIMESTAMP,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS order_items (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER REFERENCES orders(id),
                name     TEXT,
                quantity REAL,
                price    REAL,
                total    REAL
            );

            CREATE TABLE IF NOT EXISTS shipments (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                moysklad_id       TEXT UNIQUE,
                shipment_number   TEXT,
                telegram_id       INTEGER,
                customer_name     TEXT,
                customer_phone    TEXT,
                total_usd         REAL DEFAULT 0.0,
                balance_before    REAL DEFAULT 0.0,
                balance_after     REAL DEFAULT 0.0,
                status            TEXT,
                moment            TIMESTAMP,
                seller_name       TEXT,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS shipment_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_id INTEGER REFERENCES shipments(id),
                name        TEXT,
                quantity    REAL,
                price       REAL,
                total       REAL
            );

            CREATE TABLE IF NOT EXISTS returns (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                moysklad_id       TEXT UNIQUE,
                return_number     TEXT,
                telegram_id       INTEGER,
                customer_name     TEXT,
                customer_phone    TEXT,
                total_usd         REAL DEFAULT 0.0,
                balance_before    REAL DEFAULT 0.0,
                balance_after     REAL DEFAULT 0.0,
                status            TEXT,
                moment            TIMESTAMP,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS return_items (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                return_id INTEGER REFERENCES returns(id),
                name      TEXT,
                quantity  REAL,
                price     REAL,
                total     REAL
            );
        """)
        # Миграции для уже существующих баз (каждая в отдельном try)
        for migration in [
            "ALTER TABLE users ADD COLUMN moysklad_counterparty_id TEXT",
            "ALTER TABLE users ADD COLUMN balance_usd REAL DEFAULT 0.0",
            "ALTER TABLE users ADD COLUMN balance_updated_at TIMESTAMP",
            "ALTER TABLE shipments ADD COLUMN seller_name TEXT",
        ]:
            try:
                await db.execute(migration)
                await db.commit()
            except Exception:
                pass  # Колонка уже существует

        await db.commit()


# ── Users ──────────────────────────────────────────────────────────────────

async def get_user(telegram_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_user_by_phone(phone: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE phone = ?", (normalize_phone(phone),)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def register_user(telegram_id: int, phone: str, name: str, language: str = "uz") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        phone_norm = normalize_phone(phone)
        # Check if another telegram_id uses this phone
        async with db.execute("SELECT telegram_id FROM users WHERE phone = ?", (phone_norm,)) as cur:
            row = await cur.fetchone()
            if row and row[0] != telegram_id:
                await db.execute("DELETE FROM users WHERE phone = ?", (phone_norm,))

        await db.execute(
            """INSERT INTO users (telegram_id, phone, name, language)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(telegram_id) DO UPDATE SET
                 phone = excluded.phone,
                 name = excluded.name""",
            (telegram_id, phone_norm, name, language),
        )
        await db.commit()


async def save_moysklad_counterparty_id(telegram_id: int, counterparty_id: str) -> None:
    """Сохранить ID контрагента МойСклад для пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET moysklad_counterparty_id = ? WHERE telegram_id = ?",
            (counterparty_id, telegram_id),
        )
        await db.commit()


async def update_user_balance(telegram_id: int, balance: float) -> None:
    """
    Сохранить актуальный баланс пользователя (из МойСклад).
    Вызывается при каждом вебхуке: заказ, отгрузка, оплата.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE users
               SET balance_usd = ?, balance_updated_at = CURRENT_TIMESTAMP
               WHERE telegram_id = ?""",
            (balance, telegram_id),
        )
        await db.commit()


async def save_counterparty_and_balance(
    telegram_id: int,
    counterparty_id: str,
    balance: float,
) -> None:
    """Сохранить ID контрагента и баланс одним запросом."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE users
               SET moysklad_counterparty_id = ?,
                   balance_usd = ?,
                   balance_updated_at = CURRENT_TIMESTAMP
               WHERE telegram_id = ?""",
            (counterparty_id, balance, telegram_id),
        )
        await db.commit()


async def get_moysklad_counterparty_id(telegram_id: int) -> str | None:
    """Получить ID контрагента МойСклад для пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT moysklad_counterparty_id FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row and row[0] else None


async def set_user_language(telegram_id: int, language: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET language = ? WHERE telegram_id = ?",
            (language, telegram_id),
        )
        await db.commit()


async def count_users_registered_between(utc_from: str, utc_to: str) -> int:
    """Сколько пользователей прошли /start в боте за интервал.

    `registered_at` хранится в UTC (CURRENT_TIMESTAMP). На вход — UTC-границы
    в формате 'YYYY-MM-DD HH:MM:SS' (см. daily_report.run_for_today).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE registered_at BETWEEN ? AND ?",
            (utc_from, utc_to),
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def get_all_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ── Orders ─────────────────────────────────────────────────────────────────

async def save_order(
    moysklad_id: str,
    order_number: str,
    telegram_id: int | None,
    customer_name: str,
    customer_phone: str,
    total_usd: float,
    balance_usd: float,
    status: str,
    moment: str,
    items: list[dict],
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO orders
               (moysklad_id, order_number, telegram_id, customer_name, customer_phone,
                total_usd, balance_usd, status, moment)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(moysklad_id) DO UPDATE SET
                 status = excluded.status,
                 total_usd = excluded.total_usd,
                 balance_usd = excluded.balance_usd
               RETURNING id""",
            (moysklad_id, order_number, telegram_id, customer_name,
             normalize_phone(customer_phone), total_usd, balance_usd, status, moment),
        )
        row = await cur.fetchone()
        order_id = row[0]
        await db.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
        for item in items:
            await db.execute(
                "INSERT INTO order_items (order_id, name, quantity, price, total) VALUES (?,?,?,?,?)",
                (order_id, item["name"], item["quantity"], item["price"], item["total"]),
            )
        await db.commit()
        return order_id


async def get_orders_for_user(telegram_id: int, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM orders WHERE telegram_id = ? ORDER BY moment DESC LIMIT ?",
            (telegram_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_order_items(order_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM order_items WHERE order_id = ?", (order_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_orders_in_period(telegram_id: int, date_from: str, date_to: str) -> list[dict]:
    # moment хранится как '2026-04-14 18:26' — добавляем время конца дня,
    # иначе BETWEEN '2026-04-14' AND '2026-04-14' не найдёт '2026-04-14 18:26'
    date_to_end = date_to + " 23:59:59"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM orders
               WHERE telegram_id = ?
                 AND moment BETWEEN ? AND ?
               ORDER BY moment DESC""",
            (telegram_id, date_from, date_to_end),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ── Shipments ──────────────────────────────────────────────────────────────

async def save_shipment(
    moysklad_id: str,
    shipment_number: str,
    telegram_id: int | None,
    customer_name: str,
    customer_phone: str,
    total_usd: float,
    balance_before: float,
    balance_after: float,
    status: str,
    moment: str,
    items: list[dict],
    seller_name: str = "",
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO shipments
               (moysklad_id, shipment_number, telegram_id, customer_name, customer_phone,
                total_usd, balance_before, balance_after, status, moment, seller_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(moysklad_id) DO UPDATE SET
                 status = excluded.status,
                 seller_name = COALESCE(NULLIF(TRIM(excluded.seller_name), ''), shipments.seller_name)
               RETURNING id""",
            (moysklad_id, shipment_number, telegram_id, customer_name,
             normalize_phone(customer_phone), total_usd, balance_before, balance_after,
             status, moment, (seller_name or "").strip()),
        )
        row = await cur.fetchone()
        shipment_id = row[0]
        await db.execute("DELETE FROM shipment_items WHERE shipment_id = ?", (shipment_id,))
        for item in items:
            await db.execute(
                "INSERT INTO shipment_items (shipment_id, name, quantity, price, total) VALUES (?,?,?,?,?)",
                (shipment_id, item["name"], item["quantity"], item["price"], item["total"]),
            )
        await db.commit()
        return shipment_id


async def get_shipment_items(shipment_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM shipment_items WHERE shipment_id = ?", (shipment_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_shipments_for_user(telegram_id: int, limit: int = 20) -> list[dict]:
    """Otgruzkalar — faqat shu Telegram foydalanuvchisi (kontragent) bilan bog‘langan."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM shipments
               WHERE telegram_id = ?
               ORDER BY moment DESC
               LIMIT ?""",
            (telegram_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_shipments_in_period(telegram_id: int, date_from: str, date_to: str) -> list[dict]:
    date_to_end = date_to + " 23:59:59"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM shipments
               WHERE telegram_id = ?
                 AND moment BETWEEN ? AND ?
               ORDER BY moment DESC""",
            (telegram_id, date_from, date_to_end),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ── Returns ───────────────────────────────────────────────────────────────

async def save_return(
    moysklad_id: str,
    return_number: str,
    telegram_id: int | None,
    customer_name: str,
    customer_phone: str,
    total_usd: float,
    balance_before: float,
    balance_after: float,
    status: str,
    moment: str,
    items: list[dict],
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO returns
               (moysklad_id, return_number, telegram_id, customer_name, customer_phone,
                total_usd, balance_before, balance_after, status, moment)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(moysklad_id) DO UPDATE SET status = excluded.status
               RETURNING id""",
            (moysklad_id, return_number, telegram_id, customer_name,
             normalize_phone(customer_phone), total_usd, balance_before, balance_after,
             status, moment),
        )
        row = await cur.fetchone()
        return_id = row[0]
        await db.execute("DELETE FROM return_items WHERE return_id = ?", (return_id,))
        for item in items:
            await db.execute(
                "INSERT INTO return_items (return_id, name, quantity, price, total) VALUES (?,?,?,?,?)",
                (return_id, item["name"], item["quantity"], item["price"], item["total"]),
            )
        await db.commit()
        return return_id


async def get_return_items(return_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM return_items WHERE return_id = ?", (return_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_returns_in_period(telegram_id: int, date_from: str, date_to: str) -> list[dict]:
    date_to_end = date_to + " 23:59:59"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM returns
               WHERE telegram_id = ?
                 AND moment BETWEEN ? AND ?
               ORDER BY moment DESC""",
            (telegram_id, date_from, date_to_end),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ── Helpers ────────────────────────────────────────────────────────────────

def normalize_phone(phone: str) -> str:
    """Strip all non-digits, ensure starts with country code."""
    digits = "".join(c for c in phone if c.isdigit())
    # If starts with 8 and length 11 → Russian format, replace with 7
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    # If 9 digits → Uzbek local, add 998
    if len(digits) == 9:
        digits = "998" + digits
    return digits
