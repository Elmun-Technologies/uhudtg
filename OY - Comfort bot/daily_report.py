"""Дневной отчёт для админов + персональные отчёты клиентам.

Запускается по расписанию (см. scheduler.py) каждый день в 20:00 Asia/Tashkent.
Период отчёта — 00:00:00–23:59:59 текущего дня в Asia/Tashkent (МойСклад
фильтр конвертируется в МСК — Europe/Moscow).

Клиентские отчёты отправляются только пользователям у которых были
отгрузки (demand) сегодня и есть привязка к контрагенту в МойСклад.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import database as db
import moysklad_api as ms
from config import ADMIN_IDS
from locales import t
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
    """Сформировать и отправить отчёт всем ADMIN_IDS."""
    if not ADMIN_IDS:
        logger.warning("daily_report: ADMIN_IDS пуст, отчёт не отправлен")
        return
    try:
        text = await build_report_text("ru")
    except Exception as e:
        logger.exception("daily_report: build failed: %s", e)
        return
    sent = 0
    for admin_id in ADMIN_IDS:
        registered = await db.get_user(admin_id)
        if not registered:
            logger.warning(
                "daily_report: admin_id=%s is not registered in the bot — "
                "remove from ADMIN_IDS or ask them to /start first",
                admin_id,
            )
        try:
            await bot.send_message(admin_id, text)
            sent += 1
        except Exception as e:
            logger.error("daily_report: send to %s failed: %s", admin_id, e)
    logger.info("daily_report: sent to %d/%d admin(s)", sent, len(ADMIN_IDS))


async def run_customer_reports(bot) -> None:
    """Bugungi otgruzkasi bo'lgan har bir mijozga shaxsiy kunlik hisobot yuborish.

    Faqat moysklad_counterparty_id bor va bugun demand (otgruzka) bo'lgan
    foydalanuvchilarga yuboriladi.
    """
    today = local_today()
    moment_lo = f"{today.isoformat()} 00:00:00"
    moment_hi = f"{today.isoformat()} 23:59:59"
    date_label = today.strftime("%d.%m.%Y")

    try:
        users = await db.get_all_users()
    except Exception as e:
        logger.exception("customer_report: get_all_users failed: %s", e)
        return

    sent_count = 0
    for user in users:
        cp_id = user.get("moysklad_counterparty_id")
        if not cp_id:
            continue
        telegram_id = user["telegram_id"]
        lang = user.get("language") or "uz"

        try:
            shipments = await ms.fetch_demands_for_counterparty(
                cp_id,
                moment_lo=moment_lo,
                moment_hi=moment_hi,
                result_limit=None,
                max_api_scan=500,
            )
        except Exception as e:
            logger.error("customer_report: demands fetch failed user=%s: %s", telegram_id, e)
            continue

        if not shipments:
            continue

        ship_count = len(shipments)
        ship_total = sum(s["total_usd"] for s in shipments)

        try:
            balance = await ms.fetch_counterparty_balance(cp_id)
        except Exception:
            balance = float(user.get("balance_usd") or 0.0)

        try:
            text = t(
                "daily_customer_report", lang,
                date=date_label,
                ship_count=ship_count,
                ship_total=_fmt_money_ru(ship_total),
                balance=_fmt_money_ru(balance),
            )
            await bot.send_message(telegram_id, text)
            sent_count += 1
        except Exception as e:
            logger.error("customer_report: send failed user=%s: %s", telegram_id, e)

    logger.info("customer_report: sent to %d customer(s)", sent_count)
