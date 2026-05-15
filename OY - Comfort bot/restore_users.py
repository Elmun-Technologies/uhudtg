"""One-shot: восстановить локальную таблицу users из МойСклад.

Назначение: после потери SQLite-файла (например, до фикса DB_PATH /data) —
пройти по всем контрагентам в МойСклад, прочитать у них кастомный атрибут
"Telegram ID" и заново заполнить таблицу users в локальной базе.

Идемпотентно: если у пользователя уже есть запись с привязкой к
moysklad_counterparty_id — пропускаем.

Запуск внутри контейнера:
    docker exec -it <bot> python restore_users.py
"""
from __future__ import annotations

import asyncio
import logging

import database as db
from moysklad_api import MOYSKLAD_API, _get, close_moysklad_http

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("restore_users")

# UUID кастомного атрибута "Telegram ID" на сущности counterparty.
# Соответствует tg_attribute в moysklad_api.sync_counterparty.
TG_ATTR_ID = "8666aeb7-192b-11f1-0a80-00f20005e1af"


def _read_telegram_id(cp: dict) -> int | None:
    for a in cp.get("attributes") or []:
        attr_id = a.get("id") or ""
        href = (a.get("meta") or {}).get("href") or ""
        if attr_id != TG_ATTR_ID and TG_ATTR_ID not in href:
            continue
        v = a.get("value")
        if v is None:
            return None
        try:
            return int(str(v).strip())
        except (TypeError, ValueError):
            return None
    return None


async def restore() -> tuple[int, int, int, int]:
    """Returns (scanned, restored, skipped_existing, skipped_no_tg)."""
    await db.init_db()

    url = f"{MOYSKLAD_API}/entity/counterparty"
    page = 1000
    offset = 0
    scanned = 0
    restored = 0
    skipped_existing = 0
    skipped_no_tg = 0

    while True:
        params = {"limit": page, "offset": offset, "expand": "attributes"}
        try:
            data = await _get(url, params=params)
        except Exception as e:
            logger.error("MS request failed at offset=%d: %s", offset, e)
            break

        rows = data.get("rows") or []
        if not rows:
            break

        for cp in rows:
            scanned += 1
            tg_id = _read_telegram_id(cp)
            if not tg_id:
                skipped_no_tg += 1
                continue

            cp_id = cp.get("id") or ""
            phone = (cp.get("phone") or "").strip()
            name = (cp.get("name") or "").strip() or "Mijoz"

            existing = await db.get_user(tg_id)
            if existing and existing.get("moysklad_counterparty_id") == cp_id:
                skipped_existing += 1
                continue

            try:
                await db.register_user(
                    telegram_id=tg_id,
                    phone=phone if phone else str(tg_id),
                    name=name,
                    language=(existing or {}).get("language") or "uz",
                )
                if cp_id:
                    await db.save_moysklad_counterparty_id(tg_id, cp_id)
                restored += 1
                logger.info(
                    "restored tg=%s name=%r phone=%r cp=%s",
                    tg_id, name, phone, cp_id,
                )
            except Exception as e:
                logger.error("failed to restore tg=%s cp=%s: %s", tg_id, cp_id, e)

        if len(rows) < page:
            break
        offset += page
        if offset >= 100000:
            logger.warning("safety cap hit at offset=%d, stopping", offset)
            break

    return scanned, restored, skipped_existing, skipped_no_tg


async def main() -> None:
    try:
        scanned, restored, skipped_existing, skipped_no_tg = await restore()
    finally:
        await close_moysklad_http()

    print()
    print(f"Просмотрено контрагентов:        {scanned}")
    print(f"  без атрибута Telegram ID:      {skipped_no_tg}")
    print(f"  уже привязаны в локальной БД:  {skipped_existing}")
    print(f"Восстановлено пользователей:     {restored}")


if __name__ == "__main__":
    asyncio.run(main())
