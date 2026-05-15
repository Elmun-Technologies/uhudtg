from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
MOYSKLAD_TOKEN: str = os.getenv("MOYSKLAD_TOKEN", "")
WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "")
WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/moysklad/webhook")
WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8080"))
WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "secret")
DB_PATH: str = os.getenv("DB_PATH", "comfort_bot.db")
COMPANY_PHONE: str = os.getenv("COMPANY_PHONE", "+998958220000")
# IANA timezone (Asia/Tashkent = GMT+5, DST yo‘q)
APP_TIMEZONE: str = os.getenv("APP_TIMEZONE", "Asia/Tashkent")
# MoySklad har doim `moment` ni MSK (UTC+3) hisobida offset siz qaytaradi —
# uni har doim APP_TIMEZONE ga o‘giramiz. O‘chirish uchun env=none.
_naive_src = (os.getenv("MOYSKLAD_MOMENT_NAIVE_SOURCE_TZ") or "Europe/Moscow").strip()
MOYSKLAD_MOMENT_NAIVE_SOURCE_TZ: Optional[str] = (
    None
    if _naive_src.lower() in ("", "-", "none", "off", "local")
    else _naive_src
)
# 1 = har bir MS moment uchun INFO log (raw → saqlangan, qoida)
MS_MOMENT_LOG: bool = os.getenv("MS_MOMENT_LOG", "").strip().lower() in ("1", "true", "yes")


def _bounded_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int((os.getenv(name) or str(default)).strip())
        return max(lo, min(hi, v))
    except ValueError:
        return default


# MoySklad: bir vaqtda nechta enrich (owner/employee) so‘rovi
MOYSKLAD_ENRICH_CONCURRENCY: int = _bounded_int("MOYSKLAD_ENRICH_CONCURRENCY", 6, 1, 16)
# Webhook workerlar (VPS kichik bo‘lsa 2–3 qiling)
WEBHOOK_WORKERS: int = _bounded_int("WEBHOOK_WORKERS", 3, 1, 16)
_admin_env = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: list[int] = (
    [int(x.strip()) for x in _admin_env.split(",") if x.strip().isdigit()]
    if _admin_env
    else []
)

# Время дневного отчёта в Asia/Tashkent (DAILY_REPORT_HOUR:DAILY_REPORT_MINUTE)
DAILY_REPORT_HOUR: int = _bounded_int("DAILY_REPORT_HOUR", 20, 0, 23)
DAILY_REPORT_MINUTE: int = _bounded_int("DAILY_REPORT_MINUTE", 0, 0, 59)

MOYSKLAD_API = "https://api.moysklad.ru/api/remap/1.2"
