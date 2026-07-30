"""Qarzdorlik eslatmasi — haftada 2 kun (default: Chorshanba va Yakshanba).

Har bir mijozning MoySklad dagi joriy balansi olinadi; qarzi bo'lganlarga
qarz summasi + so'nggi otgruzkalar ma'lumoti bilan xabar va PDF yuboriladi.
Qarzi yo'q (yoki DEBT_MIN_AMOUNT dan kichik) mijozlar chetlab o'tiladi —
spam bo'lmasligi uchun.

Rejalashtirilgan ishga tushirish: scheduler.run_debt_reminder_loop().
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from aiogram.types import BufferedInputFile

import database as db
import moysklad_api as ms
from config import (
    COMPANY_PHONE,
    DEBT_BALANCE_SIGN,
    DEBT_HISTORY_DAYS,
    DEBT_MIN_AMOUNT,
)
from formatting import fmt_usd
from locales import t
from pdf_generator import generate_debt_notice_pdf
from time_utils import local_today

logger = logging.getLogger(__name__)

# Bir vaqtda nechta mijoz uchun MoySklad so'rovi ketadi
_CONCURRENCY = 4
BALANCE_FETCH_TIMEOUT = 25.0


def debt_from_balance(balance: float) -> float:
    """Balansdan qarz summasini ajratib olish (musbat son). Qarz bo'lmasa 0.0.

    Ishora qoidasi DEBT_BALANCE_SIGN bilan sozlanadi, chunki MoySklad
    akkauntiga qarab `report/counterparty.balance` ning ishorasi farq qiladi.
    """
    try:
        value = float(balance or 0)
    except (TypeError, ValueError):
        return 0.0
    if DEBT_BALANCE_SIGN == "positive":
        return round(value, 2) if value > 0 else 0.0
    return round(-value, 2) if value < 0 else 0.0


async def run_for_today(bot, *, force: bool = False) -> None:
    """Barcha qarzdor mijozlarga eslatma yuborish.

    force=True — bugun allaqachon eslatma olganlarga ham qaytadan yuborish.
    """
    users = await db.get_all_users()
    today = local_today()
    today_iso = today.isoformat()
    linked = [
        u for u in users
        if u.get("moysklad_counterparty_id") and u.get("telegram_id")
    ]
    if force:
        active = linked
    else:
        # Uzilib qolgan ishga tushirishni davom ettirish xavfsiz bo'lishi uchun
        # bugun eslatma olganlar chetlab o'tiladi.
        active = [u for u in linked if (u.get("debt_notified_date") or "") != today_iso]
        already = len(linked) - len(active)
        if already:
            logger.info(
                "debt_reminder: %d customer(s) already notified today, skipping",
                already,
            )
    if not active:
        logger.info("debt_reminder: no customers to notify")
        return

    date_str = today.strftime("%d.%m.%Y")
    period_from_date = today - timedelta(days=DEBT_HISTORY_DAYS - 1)
    moment_lo = f"{period_from_date.isoformat()} 00:00:00"
    moment_hi = f"{today.isoformat()} 23:59:59"
    period_from = period_from_date.strftime("%d.%m.%Y")

    sem = asyncio.Semaphore(_CONCURRENCY)
    stats = {"sent": 0, "no_debt": 0, "errored": 0}

    async def send_one(user: dict) -> None:
        async with sem:
            tg_id = int(user["telegram_id"])
            cp_id = user["moysklad_counterparty_id"]
            lang = (user.get("language") or "uz").lower()
            if lang not in ("uz", "ru"):
                lang = "uz"
            customer_name = (user.get("name") or "").strip()
            customer_phone = (user.get("phone") or "").strip()
            if customer_phone and not customer_phone.startswith("+"):
                customer_phone = "+" + customer_phone

            try:
                balance = await asyncio.wait_for(
                    ms.fetch_counterparty_balance(cp_id),
                    timeout=BALANCE_FETCH_TIMEOUT,
                )
            except Exception as e:
                logger.error("debt_reminder: balance fetch failed for user %s: %s", tg_id, e)
                stats["errored"] += 1
                return

            try:
                await db.update_user_balance(tg_id, balance)
            except Exception as e:
                logger.debug("debt_reminder: update_user_balance %s: %s", tg_id, e)

            debt = debt_from_balance(balance)
            if debt < DEBT_MIN_AMOUNT:
                stats["no_debt"] += 1
                return

            try:
                shipments = await ms.fetch_demands_for_counterparty(
                    cp_id, moment_lo=moment_lo, moment_hi=moment_hi,
                    result_limit=None, max_api_scan=2000,
                )
            except Exception as e:
                # Otgruzka tarixi bo'lmasa ham eslatmaning o'zi yuboriladi
                logger.warning("debt_reminder: shipments fetch failed for user %s: %s", tg_id, e)
                shipments = []

            ship_total = sum(float(s.get("total_usd") or 0) for s in shipments)

            text = t(
                "debt_reminder", lang,
                date=date_str,
                name=customer_name or "—",
                debt=fmt_usd(debt),
                days=DEBT_HISTORY_DAYS,
                ship_count=len(shipments),
                ship_total=fmt_usd(ship_total),
                company_phone=COMPANY_PHONE,
            )
            try:
                await bot.send_message(tg_id, text)
            except Exception as e:
                logger.error("debt_reminder: send text to user %s failed: %s", tg_id, e)
                stats["errored"] += 1
                return

            # Xabar ketdi — PDF muvaffaqiyatidan qat'i nazar belgilaymiz, aks holda
            # qayta ishga tushirishda mijoz matnni ikkinchi marta olardi.
            try:
                await db.mark_debt_notified(tg_id, today_iso)
            except Exception as e:
                logger.warning("debt_reminder: mark_debt_notified %s: %s", tg_id, e)

            try:
                pdf_bytes = await asyncio.to_thread(
                    generate_debt_notice_pdf,
                    lang=lang,
                    date_label=date_str,
                    customer_name=customer_name,
                    customer_phone=customer_phone,
                    debt_amount=debt,
                    shipments=shipments,
                    period_from=period_from,
                    period_to=date_str,
                    company_phone=COMPANY_PHONE,
                )
                filename = f"qarzdorlik_{today.strftime('%Y%m%d')}.pdf"
                await bot.send_document(
                    tg_id,
                    document=BufferedInputFile(pdf_bytes, filename=filename),
                )
            except Exception as e:
                logger.warning("debt_reminder: PDF for user %s failed: %s", tg_id, e)

            stats["sent"] += 1

    await asyncio.gather(*(send_one(u) for u in active), return_exceptions=True)
    logger.info(
        "debt_reminder: total=%d sent=%d no_debt=%d errored=%d (sign=%s, min=%.2f)",
        len(active), stats["sent"], stats["no_debt"], stats["errored"],
        DEBT_BALANCE_SIGN, DEBT_MIN_AMOUNT,
    )
