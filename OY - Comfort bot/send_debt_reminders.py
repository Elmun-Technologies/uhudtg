"""Qarzdorlik eslatmasini qo'lda ishga tushirish (rejalashtiruvchini kutmasdan).

Ikki rejim:

  # 1) FAQAT KO'RSATISH — hech kimga xabar yuborilmaydi, ro'yxat chiqadi.
  #    DEBT_BALANCE_SIGN to'g'ri sozlanganini shu yerda tekshiring.
  docker compose exec bot python send_debt_reminders.py

  # 2) HAQIQIY YUBORISH — barcha qarzdor mijozlarga xabar + PDF ketadi.
  docker compose exec bot python send_debt_reminders.py --send
"""
from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("send_debt_reminders")


async def dry_run() -> None:
    import database as db
    import moysklad_api as ms
    from config import DEBT_BALANCE_SIGN, DEBT_MIN_AMOUNT
    from debt_reminder import debt_from_balance
    from formatting import fmt_usd

    await db.init_db()
    users = await db.get_all_users()
    active = [
        u for u in users
        if u.get("moysklad_counterparty_id") and u.get("telegram_id")
    ]
    print(f"\nDEBT_BALANCE_SIGN={DEBT_BALANCE_SIGN}  DEBT_MIN_AMOUNT={DEBT_MIN_AMOUNT}")
    print(f"Kontragenti bor mijozlar: {len(active)}\n")

    sem = asyncio.Semaphore(4)
    rows: list[tuple[str, str, float, float]] = []

    async def check(user: dict) -> None:
        async with sem:
            try:
                balance = await ms.fetch_counterparty_balance(
                    user["moysklad_counterparty_id"]
                )
            except Exception as e:
                logger.error("tg=%s balans olinmadi: %s", user.get("telegram_id"), e)
                return
            rows.append((
                str(user.get("telegram_id")),
                (user.get("name") or "").strip() or "—",
                float(balance),
                debt_from_balance(balance),
            ))

    await asyncio.gather(*(check(u) for u in active), return_exceptions=True)

    debtors = [r for r in rows if r[3] >= DEBT_MIN_AMOUNT]
    debtors.sort(key=lambda r: r[3], reverse=True)

    print(f"{'tg_id':<13}{'balans':>14}{'qarz':>14}  ism")
    for tg_id, name, balance, debt in debtors:
        print(f"{tg_id:<13}{fmt_usd(balance):>14}{fmt_usd(debt):>14}  {name}")
    print(
        f"\nQarzdorlar: {len(debtors)} / {len(rows)}   "
        f"Jami qarz: {fmt_usd(sum(r[3] for r in debtors))} USD"
    )
    print("\nHaqiqiy yuborish uchun:  python send_debt_reminders.py --send\n")
    await ms.close_moysklad_http()


async def send_now() -> None:
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    import database as db
    import debt_reminder
    import moysklad_api as ms
    from config import BOT_TOKEN

    await db.init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await debt_reminder.run_for_today(bot)
    finally:
        await ms.close_moysklad_http()
        await bot.session.close()


if __name__ == "__main__":
    if "--send" in sys.argv:
        asyncio.run(send_now())
    else:
        asyncio.run(dry_run())
