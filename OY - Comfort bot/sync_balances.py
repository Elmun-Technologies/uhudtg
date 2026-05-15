"""
Одноразовый скрипт: синхронизирует балансы всех пользователей из МойСклад.
Запустить один раз: python sync_balances.py
"""

import asyncio
import sqlite3
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main():
    import httpx
    from config import MOYSKLAD_API, MOYSKLAD_TOKEN, DB_PATH

    headers = {
        "Authorization": f"Bearer {MOYSKLAD_TOKEN}",
        "Accept-Encoding": "gzip",
    }

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    users = conn.execute("SELECT telegram_id, phone FROM users").fetchall()
    logger.info("Total users: %d", len(users))

    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        for user in users:
            tg_id = user["telegram_id"]
            phone = user["phone"] or ""
            if not phone:
                logger.warning("User %s has no phone, skip", tg_id)
                continue

            digits = "".join(c for c in phone if c.isdigit())
            suffix9 = digits[-9:] if len(digits) >= 9 else digits

            # 1. Ищем контрагента по телефону
            cp_id = None
            for search_term in [f"+{digits}", digits, suffix9]:
                try:
                    r = await client.get(
                        f"{MOYSKLAD_API}/entity/counterparty",
                        params={"search": search_term, "limit": 50},
                    )
                    rows = r.json().get("rows", [])
                    for row in rows:
                        row_digits = "".join(c for c in (row.get("phone") or "") if c.isdigit())
                        if row_digits and row_digits.endswith(suffix9):
                            cp_id = row["id"]
                            logger.info("  user %s → found counterparty '%s' (id=%s)",
                                        tg_id, row.get("name"), cp_id)
                            break
                    if cp_id:
                        break
                except Exception as e:
                    logger.debug("  search '%s' error: %s", search_term, e)

            if not cp_id:
                logger.warning("  user %s (phone=%s) → counterparty NOT FOUND in MoySklad", tg_id, phone)
                continue

            # 2. Получаем баланс через POST (GET с filter= даёт 412)
            try:
                cp_href = f"{MOYSKLAD_API}/entity/counterparty/{cp_id}"
                r = await client.post(
                    f"{MOYSKLAD_API}/report/counterparty",
                    json={
                        "counterparties": [
                            {
                                "counterparty": {
                                    "meta": {
                                        "href": cp_href,
                                        "type": "counterparty",
                                        "mediaType": "application/json",
                                    }
                                }
                            }
                        ]
                    },
                )
                data = r.json()
                rows = data.get("rows", [])
                if not rows:
                    logger.warning("  user %s → empty balance report for cp=%s", tg_id, cp_id)
                    balance = 0.0
                else:
                    raw = rows[0].get("balance", 0) or 0
                    balance = round(raw / 100, 2)
                    logger.info("  user %s → balance raw=%s → %.2f USD", tg_id, raw, balance)
            except Exception as e:
                logger.error("  user %s → balance fetch error: %s", tg_id, e)
                balance = 0.0

            # 3. Сохраняем в БД
            conn.execute(
                """UPDATE users
                   SET moysklad_counterparty_id = ?,
                       balance_usd = ?,
                       balance_updated_at = CURRENT_TIMESTAMP
                   WHERE telegram_id = ?""",
                (cp_id, balance, tg_id),
            )
            conn.commit()
            logger.info("  user %s → SAVED cp_id=%s balance=%.2f", tg_id, cp_id, balance)

    # Итог
    print("\n=== Final state ===")
    users = conn.execute(
        "SELECT telegram_id, phone, moysklad_counterparty_id, balance_usd FROM users"
    ).fetchall()
    for u in users:
        print(f"  tg={u['telegram_id']}  phone={u['phone']}  balance={u['balance_usd']}  cp={'OK' if u['moysklad_counterparty_id'] else 'None'}")
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
