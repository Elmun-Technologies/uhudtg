"""Audit: MoySklad kontragentlari telefon formati — dublikat xavfini tekshirish.

Ishga tushirish:
    docker compose exec bot python audit_phones.py

Natijada:
  - Telefonsiz kontragentlar (ro'yxat)
  - Telefoni noto'g'ri formatdagi kontragentlar
  - Dublikat ehtimoli yuqori bo'lgan mijozlar
"""
from __future__ import annotations

import asyncio
import re
from collections import defaultdict

import moysklad_api as ms
from config import MOYSKLAD_API


PHONE_DIGITS_RE = re.compile(r"\D+")


def _digits(s: str | None) -> str:
    if not s:
        return ""
    return PHONE_DIGITS_RE.sub("", s)


def _phone_quality(phone_raw: str) -> str:
    """Telefon raqami formati sifati."""
    if not phone_raw or not phone_raw.strip():
        return "missing"
    digits = _digits(phone_raw)
    n = len(digits)
    if n == 0:
        return "no_digits"
    if n < 9:
        return "too_short"
    if n > 13:
        return "too_long"
    if n == 9 or n == 12:
        return "ok"
    return "non_standard"


async def fetch_all_counterparties() -> list[dict]:
    """Barcha kontragentlarni sahifalab oladi."""
    url = f"{MOYSKLAD_API}/entity/counterparty"
    rows: list[dict] = []
    offset = 0
    limit = 1000
    while True:
        resp = await ms._get(url, params={"limit": limit, "offset": offset})
        batch = resp.get("rows", [])
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
        if offset > 50000:
            break
    return rows


def find_duplicates_by_phone(rows: list[dict]) -> dict[str, list[dict]]:
    """Oxirgi 9 raqam bo'yicha guruhlash — dublikatlarni topish."""
    by_suffix: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        d = _digits(r.get("phone"))
        if len(d) >= 9:
            suffix = d[-9:]
            by_suffix[suffix].append(r)
    return {k: v for k, v in by_suffix.items() if len(v) > 1}


async def main() -> None:
    print("MoySklad'dan kontragentlar olinmoqda…")
    rows = await fetch_all_counterparties()
    print(f"Jami kontragentlar: {len(rows)}\n")

    by_quality: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        q = _phone_quality(r.get("phone", ""))
        by_quality[q].append(r)

    print("=" * 70)
    print("TELEFON FORMATI BO'YICHA STATISTIKA")
    print("=" * 70)
    total = len(rows)
    for q, items in sorted(by_quality.items(), key=lambda x: -len(x[1])):
        pct = 100.0 * len(items) / total if total else 0
        label = {
            "ok": "Standart format (9 yoki 12 raqam)",
            "missing": "Telefon umuman yo'q",
            "no_digits": "Telefonda raqam yo'q",
            "too_short": "Telefon juda qisqa (<9 raqam)",
            "too_long": "Telefon juda uzun (>13 raqam)",
            "non_standard": "Noodatiy uzunlik (10-11, 13 raqam)",
        }.get(q, q)
        print(f"  {label}: {len(items)} ta ({pct:.1f}%)")

    risky_keys = ("missing", "no_digits", "too_short", "non_standard")
    risky = [r for k in risky_keys for r in by_quality.get(k, [])]
    if risky:
        print(f"\n⚠️ DUBLIKAT XAVFI BOR — {len(risky)} ta kontragent:")
        for r in risky[:30]:
            print(f"  - {r.get('name', '—')[:40]:40} | phone='{r.get('phone', '')}'")
        if len(risky) > 30:
            print(f"  ... va yana {len(risky) - 30} ta")

    duplicates = find_duplicates_by_phone(rows)
    if duplicates:
        print(f"\n⚠️ MOYSKLAD'DA ALLAQACHON DUBLIKAT BORLAR — {len(duplicates)} ta guruh:")
        for suffix, items in list(duplicates.items())[:20]:
            print(f"\n  Telefon oxiri: ...{suffix}")
            for it in items:
                print(f"    - {it.get('name', '—')[:40]:40} | phone='{it.get('phone', '')}' | id={it.get('id')}")
        if len(duplicates) > 20:
            print(f"\n  ... va yana {len(duplicates) - 20} ta guruh")
    else:
        print("\n✅ MoySklad'da mavjud dublikatlar topilmadi (telefon bo'yicha)")

    print("\n" + "=" * 70)
    print("XULOSA")
    print("=" * 70)
    ok_count = len(by_quality.get("ok", []))
    print(f"  ✅ Bot bilan xavfsiz ishlaydi: {ok_count} ta ({100*ok_count/total:.1f}%)")
    print(f"  ⚠️ Dublikat ehtimoli bor: {len(risky)} ta ({100*len(risky)/total:.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())
