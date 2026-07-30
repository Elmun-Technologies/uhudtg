"""Простой планировщик: ежедневный / недельный запуск задач в Asia/Tashkent.

Без внешних зависимостей — только asyncio + zoneinfo.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from config import (
    DAILY_REPORT_HOUR,
    DAILY_REPORT_MINUTE,
    DEBT_REMINDER_ENABLED,
    DEBT_REMINDER_HOUR,
    DEBT_REMINDER_MINUTE,
    DEBT_REMINDER_WEEKDAYS,
)
from time_utils import LOCAL_TZ
import daily_report
import debt_reminder

logger = logging.getLogger(__name__)

_WEEKDAY_NAMES = (
    "Dushanba", "Seshanba", "Chorshanba", "Payshanba",
    "Juma", "Shanba", "Yakshanba",
)


def _seconds_until_next(hour: int, minute: int) -> float:
    now = datetime.now(LOCAL_TZ)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


def _next_weekly_run(
    weekdays: tuple[int, ...], hour: int, minute: int
) -> datetime | None:
    """Ближайший запуск строго в будущем для набора дней недели (Пн=0…Вс=6)."""
    if not weekdays:
        return None
    now = datetime.now(LOCAL_TZ)
    for shift in range(0, 8):
        candidate = (now + timedelta(days=shift)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate <= now or candidate.weekday() not in weekdays:
            continue
        return candidate
    return None


async def run_daily_report_loop(bot) -> None:
    """Бесконечный цикл: ждать до DAILY_REPORT_HOUR:MM Asia/Tashkent → отправить отчёт."""
    while True:
        delay = _seconds_until_next(DAILY_REPORT_HOUR, DAILY_REPORT_MINUTE)
        logger.info(
            "daily_report scheduler: next run in %.0f sec (at %02d:%02d %s)",
            delay, DAILY_REPORT_HOUR, DAILY_REPORT_MINUTE, LOCAL_TZ,
        )
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            logger.info("daily_report scheduler cancelled")
            return
        try:
            await daily_report.run_for_today(bot)
        except Exception as e:
            logger.exception("daily_report run failed: %s", e)
        # на случай если отчёт отработал быстрее минуты — подождём,
        # чтобы не уйти на повторный запуск в ту же минуту
        await asyncio.sleep(61)


async def run_debt_reminder_loop(bot) -> None:
    """Напоминание о задолженности — по DEBT_REMINDER_WEEKDAYS (по умолчанию Ср и Вс)."""
    if not DEBT_REMINDER_ENABLED:
        logger.info("debt_reminder scheduler: disabled (DEBT_REMINDER_ENABLED=0)")
        return
    if not DEBT_REMINDER_WEEKDAYS:
        logger.warning("debt_reminder scheduler: DEBT_REMINDER_WEEKDAYS empty, not started")
        return

    days_label = ", ".join(
        _WEEKDAY_NAMES[d] for d in DEBT_REMINDER_WEEKDAYS if 0 <= d <= 6
    )
    while True:
        target = _next_weekly_run(
            DEBT_REMINDER_WEEKDAYS, DEBT_REMINDER_HOUR, DEBT_REMINDER_MINUTE
        )
        if target is None:
            logger.warning("debt_reminder scheduler: no upcoming run resolved, stopping")
            return
        delay = (target - datetime.now(LOCAL_TZ)).total_seconds()
        logger.info(
            "debt_reminder scheduler: next run in %.0f sec (%s at %02d:%02d %s; days=%s)",
            delay, target.strftime("%Y-%m-%d"),
            DEBT_REMINDER_HOUR, DEBT_REMINDER_MINUTE, LOCAL_TZ, days_label,
        )
        try:
            await asyncio.sleep(max(0.0, delay))
        except asyncio.CancelledError:
            logger.info("debt_reminder scheduler cancelled")
            return
        try:
            await debt_reminder.run_for_today(bot)
        except Exception as e:
            logger.exception("debt_reminder run failed: %s", e)
        # чтобы не попасть в ту же минуту второй раз
        await asyncio.sleep(61)
