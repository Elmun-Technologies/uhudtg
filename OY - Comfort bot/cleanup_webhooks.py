"""One-shot: удалить ВСЕ вебхуки в МойСклад.

После запуска MS-аккаунт остаётся без вебхуков — нужно сразу выполнить
register_webhooks.py, чтобы создать нужные.

Назначение: убрать накопившийся «мусор» (десятки старых записей на
ngrok-URL, мёртвые api-ct-shopbot.oymoysklad.com, functions.yandexcloud.net
и т.д.), чтобы МойСклад не пытался достучаться до несуществующих хостов.

Запуск:
    docker compose exec bot python cleanup_webhooks.py
"""
from __future__ import annotations

import asyncio
import logging

from moysklad_api import MOYSKLAD_API, _get, _shared_http, close_moysklad_http

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("cleanup_webhooks")


async def delete_all() -> tuple[int, int]:
    url = f"{MOYSKLAD_API}/entity/webhook"
    try:
        resp = await _get(url)
    except Exception as e:
        logger.error("Не удалось получить список вебхуков: %s", e)
        return 0, 0

    rows = resp.get("rows") or []
    if not rows:
        logger.info("Список вебхуков пуст — удалять нечего.")
        return 0, 0

    logger.info("Найдено %d вебхуков. Удаляю все…", len(rows))

    client = await _shared_http()
    deleted = 0
    failed = 0
    for w in rows:
        href = (w.get("meta") or {}).get("href")
        if not href:
            continue
        action = w.get("action")
        entity = w.get("entityType")
        target = (w.get("url") or "")[:70]
        try:
            r = await client.delete(href)
            r.raise_for_status()
            deleted += 1
            print(f"  ✓ {action:8s} {entity:18s} → {target}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {action:8s} {entity:18s} → {target}  ({e})")

    return deleted, failed


async def main() -> None:
    try:
        deleted, failed = await delete_all()
    finally:
        await close_moysklad_http()
    print()
    print(f"Удалено вебхуков: {deleted}")
    if failed:
        print(f"Ошибок:          {failed}")
    print()
    print("Теперь запустите:  python register_webhooks.py")


if __name__ == "__main__":
    asyncio.run(main())
