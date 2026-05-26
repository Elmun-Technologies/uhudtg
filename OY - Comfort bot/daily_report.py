"""Дневной отчёт для админов + рассылка персональных отчётов клиентам.

Запускается по расписанию (см. scheduler.py) каждый день в 20:00 Asia/Tashkent.
Период отчёта — 00:00:00–23:59:59 текущего дня в Asia/Tashkent (МойСклад
фильтр конвертируется в МСК — Europe/Moscow).

Клиенты, у которых сегодня не было активности (нет отгрузок и возвратов),
сообщение НЕ получают — чтобы не спамить ежедневно.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.types import BufferedInputFile

import database as db
import moysklad_api as ms
from config import ADMIN_IDS
from formatting import fmt_usd
from locales import t
from pdf_generator import generate_period_report_pdf
from time_utils import LOCAL_TZ, local_today

logger = logging.getLogger(__name__)

_MSK = ZoneInfo("Europe/Moscow")
_UTC = ZoneInfo("UTC")


def _fmt_money_ru(v: float) -> str:
    """8639.78 → '8 639,78' (NBSP thousand sep, comma decimal)."""
    s = f"{float(v):,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", " ")


def _today_bounds() -> tuple[str, str, str, str, str]:
    """Returns (msk_from, msk_to, utc_from, utc_to, ddmmyyyy_local)."""
    today = local_today()
    start_local = datetime.combine(today, datetime.min.time(), tzinfo=LOCAL_TZ)
    end_local = start_local + timedelta(days=1) - timedelta(seconds=1)

    fmt = "%Y-%m-%d %H:%M:%S"
    msk_from = start_local.astimezone(_MSK).strftime(fmt)
    msk_to = end_local.astimezone(_MSK).strftime(fmt)
    utc_from = start_local.astimezone(_UTC).strftime(fmt)
    utc_to = end_local.astimezone(_UTC).strftime(fmt)
    return msk_from, msk_to, utc_from, utc_to, today.strftime("%d.%m.%Y")


async def build_report_text(lang: str = "ru") -> str:
    msk_from, msk_to, utc_from, utc_to, date_label = _today_bounds()

    entity_types = (
        "customerorder",
        "demand",
        "paymentin",
        "cashin",
        "paymentout",
        "cashout",
        "supply",
    )
    results = await asyncio.gather(
        *(
            ms.aggregate_documents(
                e, moment_from_msk=msk_from, moment_to_msk=msk_to
            )
            for e in entity_types
        ),
        ms.count_new_counterparties(
            created_from_msk=msk_from, created_to_msk=msk_to
        ),
        db.count_users_registered_between(utc_from, utc_to),
        return_exceptions=True,
    )

    def _ok(r) -> tuple[int, float]:
        if isinstance(r, Exception):
            logger.error("daily_report aggregate piece failed: %s", r)
            return 0, 0.0
        return r

    def _ok_int(r) -> int:
        if isinstance(r, Exception):
            logger.error("daily_report counter failed: %s", r)
            return 0
        return int(r)

    orders = _ok(results[0])
    ship = _ok(results[1])
    paymin = _ok(results[2])
    cashin = _ok(results[3])
    paymout = _ok(results[4])
    cashout = _ok(results[5])
    supply = _ok(results[6])
    new_cp_ms = _ok_int(results[7])
    new_cp_bot = _ok_int(results[8])

    return t(
        "daily_admin_report", lang,
        date=date_label,
        orders_count=orders[0], orders_total=_fmt_money_ru(orders[1]),
        ship_count=ship[0], ship_total=_fmt_money_ru(ship[1]),
        paymentin_count=paymin[0], paymentin_total=_fmt_money_ru(paymin[1]),
        cashin_count=cashin[0], cashin_total=_fmt_money_ru(cashin[1]),
        paymentout_count=paymout[0], paymentout_total=_fmt_money_ru(paymout[1]),
        cashout_count=cashout[0], cashout_total=_fmt_money_ru(cashout[1]),
        supply_count=supply[0], supply_total=_fmt_money_ru(supply[1]),
        new_cp_ms=new_cp_ms,
        new_cp_bot=new_cp_bot,
    )


async def run_for_today(bot) -> None:
    """
    Сформировать и отправить:
      1) сводный отчёт всем ADMIN_IDS
      2) персональные отчёты каждому клиенту, у которого сегодня была активность
    """
    if ADMIN_IDS:
        try:
            text = await build_report_text("ru")
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, text)
                except Exception as e:
                    logger.error("daily_report: send to admin %s failed: %s", admin_id, e)
            logger.info("daily_report: sent to %d admin(s)", len(ADMIN_IDS))
        except Exception as e:
            logger.exception("daily_report: admin build failed: %s", e)
    else:
        logger.info("daily_report: ADMIN_IDS empty, admin report skipped")

    try:
        await send_to_customers(bot)
    except Exception as e:
        logger.exception("daily_report: customers broadcast failed: %s", e)


async def send_to_customers(bot) -> None:
    """Каждому клиенту с привязанным контрагентом — персональный дневной отчёт.

    Клиенты без активности за сегодня пропускаются молча.
    """
    users = await db.get_all_users()
    active = [u for u in users if u.get("moysklad_counterparty_id") and u.get("telegram_id")]
    if not active:
        logger.info("daily_report: no customers with counterparty to notify")
        return

    today = local_today()
    date_str = today.strftime("%d.%m.%Y")
    moment_lo = f"{today.isoformat()} 00:00:00"
    moment_hi = f"{today.isoformat()} 23:59:59"

    sem = asyncio.Semaphore(4)
    stats = {"sent": 0, "skipped": 0, "errored": 0}

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
                shipments, returns = await asyncio.gather(
                    ms.fetch_demands_for_counterparty(
                        cp_id, moment_lo=moment_lo, moment_hi=moment_hi,
                        result_limit=None, max_api_scan=2000,
                    ),
                    ms.fetch_salesreturns_for_counterparty(
                        cp_id, moment_lo=moment_lo, moment_hi=moment_hi,
                        result_limit=None, max_api_scan=2000,
                    ),
                )
            except Exception as e:
                logger.error("daily_report: fetch failed for user %s: %s", tg_id, e)
                stats["errored"] += 1
                return

            if not shipments and not returns:
                stats["skipped"] += 1
                return

            ship_total = sum(s["total_usd"] for s in shipments)
            ret_total = sum(r["total_usd"] for r in returns)
            period_label = "Kunlik" if lang == "uz" else "Дневной"

            text = t(
                "report_result", lang,
                period_label=period_label,
                date_from=date_str, date_to=date_str,
                ship_count=len(shipments), ship_total=fmt_usd(ship_total),
                ret_count=len(returns), ret_total=fmt_usd(ret_total),
                total=fmt_usd(ship_total - ret_total),
                items="",
            )
            try:
                await bot.send_message(tg_id, text)
            except Exception as e:
                logger.error("daily_report: send text to user %s failed: %s", tg_id, e)
                stats["errored"] += 1
                return

            try:
                pdf_bytes = await asyncio.to_thread(
                    generate_period_report_pdf,
                    lang=lang,
                    period_label=period_label,
                    date_from=date_str, date_to=date_str,
                    customer_name=customer_name,
                    customer_phone=customer_phone,
                    shipments=shipments,
                    returns=returns,
                    ship_total=ship_total,
                    ret_total=ret_total,
                    aggregated_items=[],
                )
                filename = f"hisobot_kunlik_{today.strftime('%Y%m%d')}.pdf"
                await bot.send_document(
                    tg_id,
                    document=BufferedInputFile(pdf_bytes, filename=filename),
                )
            except Exception as e:
                logger.warning("daily_report: PDF for user %s failed: %s", tg_id, e)

            stats["sent"] += 1

    await asyncio.gather(
        *(send_one(u) for u in active), return_exceptions=True
    )
    logger.info(
        "daily_report customers: total=%d sent=%d skipped(no activity)=%d errored=%d",
        len(active), stats["sent"], stats["skipped"], stats["errored"],
    )
