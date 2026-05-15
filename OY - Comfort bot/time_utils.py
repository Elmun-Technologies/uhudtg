from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import APP_TIMEZONE, MOYSKLAD_MOMENT_NAIVE_SOURCE_TZ


def _resolve_local_tz():
    try:
        return ZoneInfo(APP_TIMEZONE)
    except Exception:
        return timezone(timedelta(hours=5))


LOCAL_TZ = _resolve_local_tz()


def local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def local_today() -> date:
    return local_now().date()


def _normalize_moysklad_moment(raw: str | None) -> tuple[str, str]:
    """
    MS `moment` → `APP_TIMEZONE` (masalan Asia/Tashkent) bo‘yicha devoriy qator.

    API offset (+03, Z, +05) bilan kelsa — APP_TIMEZONE ga aylantiriladi.

    Offset yo‘q (naive) bo‘lsa defaultda literal qoldiriladi. Xohlansa
    ``MOYSKLAD_MOMENT_NAIVE_SOURCE_TZ`` bilan manba zona beriladi (masalan
    ``Europe/Moscow``), keyin APP_TIMEZONE ga aylantiriladi.
    """
    if not raw:
        return "", "empty"
    s = str(raw).strip().replace("Z", "+00:00").replace("z", "+00:00")
    if len(s) >= 11 and s[10] == " " and "T" not in s[:11]:
        s = s[:10] + "T" + s[11:]
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        s2 = str(raw).strip().replace("T", " ", 1)
        if "." in s2:
            s2 = s2.split(".", 1)[0]
        if len(s2) >= 19:
            return s2[:19], "fallback"
        if len(s2) >= 16:
            return s2[:16], "fallback"
        return s2, "fallback"

    if dt.tzinfo is not None:
        dt = dt.astimezone(LOCAL_TZ).replace(tzinfo=None)
        rule = "to_app_timezone"
    elif MOYSKLAD_MOMENT_NAIVE_SOURCE_TZ:
        try:
            src = ZoneInfo(MOYSKLAD_MOMENT_NAIVE_SOURCE_TZ)
            dt = dt.replace(tzinfo=src).astimezone(LOCAL_TZ).replace(tzinfo=None)
            rule = f"naive_via_{MOYSKLAD_MOMENT_NAIVE_SOURCE_TZ}"
        except Exception:
            rule = "naive_literal"
    else:
        rule = "naive_literal"
    if dt.second or dt.microsecond:
        return dt.strftime("%Y-%m-%d %H:%M:%S"), rule
    return dt.strftime("%Y-%m-%d %H:%M"), rule


def normalize_moysklad_moment_wallclock(raw: str | None) -> str:
    """MoySklad `moment` → ixcham qator (offset / naive MS zonasi → APP_TIMEZONE)."""
    compact, _ = _normalize_moysklad_moment(raw)
    return compact
