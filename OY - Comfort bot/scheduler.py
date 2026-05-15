"""Простой планировщик: ежедневный запуск задачи в указанный час Asia/Tashkent.

Без внешних зависимостей — только asyncio + zoneinfo.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from config import DAILY_REPORT_HOUR, DAILY_REPORT_MINUTE
from time_utils import LOCAL_TZ
import daily_report

logger = logging.getLogger(__name__)


def _seconds_until_next(hour: int, minute: int) -> float:
    now = datetime.now(LOCAL_TZ)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


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
