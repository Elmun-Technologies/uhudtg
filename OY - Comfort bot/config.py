from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
MOYSKLAD_TOKEN: str = os.getenv("MOYSKLAD_TOKEN", "")
# UUID maxsus atributi "Telegram ID" — yangi kontragentni yaratayotganda
# qaysi atributga telegram_id yoziladi. Akkauntga ko'ra o'zgaradi:
# `docker compose exec bot python list_attributes.py` orqali topish mumkin.
# Bo'sh qoldirilsa — yangi kontragent yaratish atributsiz amalga oshadi.
MOYSKLAD_TG_ATTR_UUID: str = os.getenv(
    "MOYSKLAD_TG_ATTR_UUID", "0db9b9e1-bd23-11ef-0a80-045400574ee9"
)
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


def _bool_env(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _weekdays_env(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    """'2,6' → (2, 6). Python weekday(): Dushanba=0 … Yakshanba=6."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    days = sorted({
        int(part)
        for part in (p.strip() for p in raw.split(","))
        if part.isdigit() and 0 <= int(part) <= 6
    })
    return tuple(days) or default


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

# ── Qarzdorlik eslatmasi (haftada 2 kun) ────────────────────────────────────
DEBT_REMINDER_ENABLED: bool = _bool_env("DEBT_REMINDER_ENABLED", True)
# Python weekday(): Dushanba=0, Seshanba=1, Chorshanba=2 … Yakshanba=6
DEBT_REMINDER_WEEKDAYS: tuple[int, ...] = _weekdays_env("DEBT_REMINDER_WEEKDAYS", (2, 6))
DEBT_REMINDER_HOUR: int = _bounded_int("DEBT_REMINDER_HOUR", 10, 0, 23)
DEBT_REMINDER_MINUTE: int = _bounded_int("DEBT_REMINDER_MINUTE", 0, 0, 59)
# MoySklad `report/counterparty.balance` da qarzdorlik qaysi ishora bilan
# ko'rsatiladi: "negative" → balans manfiy bo'lsa qarz, "positive" → musbat
# bo'lsa qarz. Akkauntga qarab farq qiladi — bir mijozda tekshirib sozlang.
DEBT_BALANCE_SIGN: str = (
    "positive"
    if (os.getenv("DEBT_BALANCE_SIGN") or "").strip().lower().startswith("pos")
    else "negative"
)
# Shu summadan kichik qarzga eslatma yuborilmaydi (tiyin-qoldiqlarni filtrlash)
try:
    DEBT_MIN_AMOUNT: float = max(0.0, float((os.getenv("DEBT_MIN_AMOUNT") or "1").strip()))
except ValueError:
    DEBT_MIN_AMOUNT = 1.0
# Eslatmaga ilova qilinadigan otgruzkalar tarixi (kun)
DEBT_HISTORY_DAYS: int = _bounded_int("DEBT_HISTORY_DAYS", 90, 1, 730)

MOYSKLAD_API = "https://api.moysklad.ru/api/remap/1.2"
