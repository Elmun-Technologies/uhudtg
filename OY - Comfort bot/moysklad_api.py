"""MoySklad API client (async)."""
from __future__ import annotations

import asyncio
import logging
import httpx
from config import (
    MOYSKLAD_API,
    MOYSKLAD_ENRICH_CONCURRENCY,
    MOYSKLAD_TG_ATTR_UUID,
    MOYSKLAD_TOKEN,
    MS_MOMENT_LOG,
)

logger = logging.getLogger(__name__)

_http_lock: asyncio.Lock | None = None
_http_client: httpx.AsyncClient | None = None


def _to_default_amount(sum_minor, rate) -> float:
    """Convert a MoySklad sum from doc-currency minor units (kopecks/tijin)
    to account default currency main units (e.g. USD).

    MoySklad: amount_in_default_currency = (sum / 100) * rate.value
    Если rate.value отсутствует — документ оформлен в валюте по умолчанию,
    factor=1.
    """
    if not sum_minor:
        return 0.0
    factor = 1.0
    if isinstance(rate, dict):
        v = rate.get("value")
        if v is not None:
            try:
                factor = float(v)
            except (TypeError, ValueError):
                factor = 1.0
    return round((float(sum_minor) / 100.0) * factor, 2)


def _to_original_amount(sum_minor) -> float:
    """Sum in document's own currency main units (NOT converted), e.g. сум."""
    if not sum_minor:
        return 0.0
    return round(float(sum_minor) / 100.0, 2)


def _doc_currency_name(rate) -> str:
    """Display name of document currency from rate.currency.name (e.g. 'сум', 'USD')."""
    if isinstance(rate, dict):
        cur = rate.get("currency") or {}
        name = (cur.get("name") or "").strip()
        if name:
            return name
    return "USD"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {MOYSKLAD_TOKEN}",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
    }


async def _shared_http() -> httpx.AsyncClient:
    """Bitta AsyncClient — har so‘rovda TLS qayta ochilmaydi (server/VPS uchun)."""
    global _http_client, _http_lock
    if _http_lock is None:
        _http_lock = asyncio.Lock()
    async with _http_lock:
        if _http_client is None or _http_client.is_closed:
            _http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(25.0, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=8, max_connections=12),
                headers=_headers(),
            )
        return _http_client


async def close_moysklad_http() -> None:
    """bot.py finally: ulanishlarni yopish."""
    global _http_client, _http_lock
    if _http_lock is None:
        return
    async with _http_lock:
        if _http_client is not None:
            await _http_client.aclose()
            _http_client = None


# ── Global rate limiting + retry ─────────────────────────────────────────────
# MoySklad cheklovi: ~45 so‘rov / 3 sekund va bir vaqtdagi ulanishlar soni
# cheklangan. Telegram'da bir necha mijoz bir zumda /start bossa (har biri
# 3–5 ta API so‘rov), throttle qilinmagan portlash MoySklad himoyasini ishga
# tushiradi (HTTP 403 kod=1073/1074 yoki 429), ba'zan API vaqtincha bloklanadi.
# Shuning uchun: global concurrency cheklanadi, so‘rovlar orasiga minimal
# interval qo‘yiladi, throttle javoblari exponential backoff bilan qaytariladi.
_MS_MAX_CONCURRENCY = 3
_MS_MIN_INTERVAL = 0.10  # so‘rov boshlanishlari orasidagi minimal vaqt (~10 req/s)
_MS_MAX_RETRIES = 4

_ms_semaphore: asyncio.Semaphore | None = None
_ms_rate_lock: asyncio.Lock | None = None
_ms_last_request_ts: float = 0.0


def _ensure_throttle() -> tuple[asyncio.Semaphore, asyncio.Lock]:
    global _ms_semaphore, _ms_rate_lock
    if _ms_semaphore is None:
        _ms_semaphore = asyncio.Semaphore(_MS_MAX_CONCURRENCY)
    if _ms_rate_lock is None:
        _ms_rate_lock = asyncio.Lock()
    return _ms_semaphore, _ms_rate_lock


async def _pace() -> None:
    """Global ravishda so‘rovlar orasida _MS_MIN_INTERVAL ni ta'minlaydi."""
    global _ms_last_request_ts
    _, rate_lock = _ensure_throttle()
    async with rate_lock:
        loop = asyncio.get_running_loop()
        now = loop.time()
        wait = _ms_last_request_ts + _MS_MIN_INTERVAL - now
        if wait > 0:
            await asyncio.sleep(wait)
            now = loop.time()
        _ms_last_request_ts = now


def _is_throttle_response(exc: httpx.HTTPStatusError) -> bool:
    """True — agar xato vaqtinchalik throttle bo‘lsa (qayta urinish xavfsiz)."""
    status = exc.response.status_code
    if status == 429 or 500 <= status < 600:
        return True
    if status == 403:
        # MoySklad rate/ulanish limitida ham 403 qaytaradi (kod 1073/1074).
        # 1061 (API kirishi yo‘q) — qayta urinilmaydi, sozlama muammosi.
        try:
            errors = exc.response.json().get("errors", [])
            codes = {e.get("code") for e in errors}
            return bool(codes & {1073, 1074})
        except Exception:
            return False
    return False


async def _request(method: str, url: str, *, params=None, json_data=None) -> dict:
    sem, _ = _ensure_throttle()
    client = await _shared_http()
    last_exc: Exception | None = None
    for attempt in range(_MS_MAX_RETRIES):
        async with sem:
            await _pace()
            resp = await client.request(method, url, params=params, json=json_data)
        try:
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if not _is_throttle_response(exc) or attempt == _MS_MAX_RETRIES - 1:
                raise
            backoff = 2 ** attempt  # 1, 2, 4, 8 sekund
            logger.warning(
                "MoySklad throttled (%s), retry %d/%d after %ds: %s",
                exc.response.status_code, attempt + 1, _MS_MAX_RETRIES, backoff, url,
            )
            await asyncio.sleep(backoff)
    if last_exc:
        raise last_exc
    raise RuntimeError("unreachable")


async def _get(url: str, params: dict | None = None) -> dict:
    return await _request("GET", url, params=params)


async def _post(url: str, json_data: dict | None = None) -> dict:
    return await _request("POST", url, json_data=json_data)


async def _put(url: str, json_data: dict | None = None) -> dict:
    return await _request("PUT", url, json_data=json_data)


async def sync_counterparty(name: str, phone: str, telegram_id: int) -> dict:
    """
    Найти контрагента по телефону и добавить Telegram ID в атрибуты.

    ВАЖНО: если контрагент уже существует — обновляем ТОЛЬКО атрибут telegram_id,
    не трогая имя и телефон (они управляются менеджером в МойСклад).
    Если контрагент не найден — создаём нового.

    Telegram ID атрибут — кастомный атрибут в МойСклад. UUID меняется от
    аккаунта к аккаунту (см. config.MOYSKLAD_TG_ATTR_UUID). Если атрибут
    не существует в этом аккаунте (404), контрагент создаётся БЕЗ атрибута —
    регистрация клиента не должна срываться из-за отсутствия атрибута.
    """
    url = f"{MOYSKLAD_API}/entity/counterparty"

    try:
        # Prefer robust multi-format search to avoid duplicate counterparties.
        existing_cp_id = await find_counterparty_id_by_phone(phone)
        if existing_cp_id:
            matched = await _get(f"{url}/{existing_cp_id}")
            logger.info(
                "Found existing counterparty '%s' (id=%s) by phone — no new counterparty created",
                matched.get("name"), existing_cp_id,
            )
            return matched

        logger.info("Counterparty not found for phone %s, creating new", phone)
        base_data: dict = {"name": name, "phone": phone}

        # Birinchi urinish — Telegram ID atributi bilan
        if MOYSKLAD_TG_ATTR_UUID:
            tg_attribute = {
                "meta": {
                    "href": (
                        f"{MOYSKLAD_API}/entity/counterparty/metadata/"
                        f"attributes/{MOYSKLAD_TG_ATTR_UUID}"
                    ),
                    "type": "attributemetadata",
                    "mediaType": "application/json",
                },
                "value": str(telegram_id),
            }
            try:
                return await _post(url, json_data={**base_data, "attributes": [tg_attribute]})
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 404:
                    raise
                logger.warning(
                    "Telegram ID atribut topilmadi (UUID=%s, 404). "
                    "Kontragent atributsiz yaratiladi. config.py / .env'da "
                    "MOYSKLAD_TG_ATTR_UUID ni to'g'rilash kerak.",
                    MOYSKLAD_TG_ATTR_UUID,
                )

        # Fallback: atributsiz yaratish — mijoz baribir ro'yxatga olinadi
        return await _post(url, json_data=base_data)

    except Exception as e:
        logger.error("sync_counterparty error for phone %s: %s", phone, e)
        raise


async def update_counterparty_address(counterparty_id: str, address: str) -> dict:
    """Update the actualAddress field of a MoySklad counterparty."""
    url = f"{MOYSKLAD_API}/entity/counterparty/{counterparty_id}"
    return await _put(url, json_data={"actualAddress": address})


async def reverse_geocode(lat: float, lon: float) -> str:
    """Convert GPS coordinates to a human-readable address via Nominatim.

    Falls back to plain coordinates if the request fails.
    """
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {"lat": lat, "lon": lon, "format": "json", "accept-language": "uz,ru,en"}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0),
            headers={"User-Agent": "UhudAutoBot/1.0"},
        ) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            display = (data.get("display_name") or "").strip()
            if display:
                return display
    except Exception as e:
        logger.warning("reverse_geocode failed (%.6f, %.6f): %s", lat, lon, e)
    return f"{lat:.6f}, {lon:.6f}"


async def fetch_entity(href: str) -> dict:
    """Fetch any MoySklad entity by its full href URL."""
    params = {
        "expand": (
            "agent,positions.assortment,store,rate.currency,owner,salesChannel,attributes"
        ),
        "limit": 100,
    }
    return await _get(href, params=params)


def parse_payment(data: dict, payment_type: str) -> dict:
    """Parse cashin/paymentin/cashout/paymentout response.

    Direction:
      • cashin / paymentin  — мы получили деньги (приход)
      • cashout / paymentout — мы выплатили деньги (расход)
    """
    agent = data.get("agent", {}) or {}
    agent_phone = agent.get("phone", "")
    rate = data.get("rate")
    # Сумму платежа показываем клиенту в валюте документа.
    amount_original = _to_original_amount(data.get("sum"))

    currency_name = _doc_currency_name(rate)

    is_cash = payment_type in ("cashin", "cashout")
    method = "Наличные" if is_cash else "Электронные"
    method_uz = "Naqd pul" if is_cash else "Elektron"
    direction = "in" if payment_type in ("cashin", "paymentin") else "out"

    return {
        "moysklad_id": data.get("id", ""),
        "payment_number": data.get("name", ""),
        "moment": _moment_compact_storage(data.get("moment")),
        "agent_name": agent.get("name", ""),
        "agent_phone": agent_phone,
        "agent_id": _extract_id(agent.get("meta", {}).get("href", "")),
        "amount": amount_original,
        "currency": currency_name,
        "payment_method_ru": method,
        "payment_method_uz": method_uz,
        "direction": direction,
        "payment_type": payment_type,
    }


async def fetch_counterparty(href: str) -> dict:
    """Fetch a counterparty (agent) by href."""
    return await _get(href)


async def find_counterparty_by_phone(phone: str) -> dict | None:
    """
    Найти контрагента в МойСклад по телефону и вернуть его id + actualAddress.

    Возвращает: {"id": str, "actualAddress": str} либо None если не найден.
    Используется при регистрации, чтобы решить — нужно ли запрашивать адрес.
    """
    url = f"{MOYSKLAD_API}/entity/counterparty"
    phone_digits = "".join(c for c in phone if c.isdigit())
    if not phone_digits:
        return None

    suffix9 = phone_digits[-9:]

    search_variants = list(dict.fromkeys([
        f"+{phone_digits}",
        phone_digits,
        suffix9,
    ]))

    for search_term in search_variants:
        try:
            resp = await _get(url, params={"search": search_term, "limit": 50})
            rows = resp.get("rows", [])
            for row in rows:
                row_phone_d = "".join(c for c in (row.get("phone") or "") if c.isdigit())
                if row_phone_d and row_phone_d.endswith(suffix9):
                    return {
                        "id": row.get("id") or "",
                        "actualAddress": (row.get("actualAddress") or "").strip(),
                        "name": row.get("name") or "",
                    }
        except Exception as e:
            logger.debug("Search '%s' failed: %s", search_term, e)

    return None


async def find_counterparty_id_by_phone(phone: str) -> str | None:
    """
    Найти ID контрагента в МойСклад по номеру телефона.

    Использует те же поисковые запросы что и sync_counterparty —
    гарантированно работает, т.к. sync_counterparty уже находил контрагентов.
    """
    url = f"{MOYSKLAD_API}/entity/counterparty"
    phone_digits = "".join(c for c in phone if c.isdigit())
    if not phone_digits:
        return None

    suffix9 = phone_digits[-9:]  # последние 9 цифр для сравнения

    # Несколько форматов поиска — от точного к широкому
    search_variants = list(dict.fromkeys([
        f"+{phone_digits}",   # +998909623393  (как в sync_counterparty — точно работает)
        phone_digits,          # 998909623393
        suffix9,               # 909623393
    ]))

    for search_term in search_variants:
        try:
            resp = await _get(url, params={"search": search_term, "limit": 50})
            rows = resp.get("rows", [])
            for row in rows:
                row_phone_d = "".join(c for c in (row.get("phone") or "") if c.isdigit())
                if row_phone_d and row_phone_d.endswith(suffix9):
                    cp_id = row.get("id")
                    logger.info(
                        "find_counterparty_id_by_phone: found '%s' (id=%s) via search '%s'",
                        row.get("name"), cp_id, search_term,
                    )
                    return cp_id
        except Exception as e:
            logger.debug("Search '%s' failed: %s", search_term, e)

    logger.warning("find_counterparty_id_by_phone: NOT FOUND for phone=%s", phone)
    return None


async def fetch_counterparty_balance(counterparty_id: str) -> float:
    """
    Получить баланс взаиморасчётов контрагента из отчёта МойСклад.

    POST /report/counterparty  (GET с filter= даёт 412, используем POST)
    rows[0].balance — в копейках (1/100 валюты): -786 → -7.86 USD

    Raises httpx.HTTPStatusError on API errors so callers can handle them.
    """
    counterparty_href = f"{MOYSKLAD_API}/entity/counterparty/{counterparty_id}"
    url = f"{MOYSKLAD_API}/report/counterparty"
    body = {
        "counterparties": [
            {
                "counterparty": {
                    "meta": {
                        "href": counterparty_href,
                        "type": "counterparty",
                        "mediaType": "application/json",
                    }
                }
            }
        ]
    }
    data = await _post(url, json_data=body)
    rows = data.get("rows", [])
    logger.debug("fetch_counterparty_balance: cp=%s rows_count=%d", counterparty_id, len(rows))
    if not rows:
        logger.warning("fetch_counterparty_balance: empty rows for cp=%s", counterparty_id)
        return 0.0
    row = rows[0]
    balance_raw = row.get("balance", 0) or 0
    balance = round(balance_raw / 100, 2)
    logger.debug("fetch_counterparty_balance: cp=%s raw=%s → %.2f USD", counterparty_id, balance_raw, balance)
    return balance


def _agent_filter(counterparty_id: str) -> str:
    href = f"{MOYSKLAD_API}/entity/counterparty/{counterparty_id}"
    return f"agent={href}"


def _moment_cmp_key(moment_compact: str) -> str:
    if not moment_compact:
        return ""
    s = str(moment_compact).strip().replace("T", " ")
    if len(s) >= 19:
        return s[:19]
    if len(s) == 16:
        return s + ":00"
    if len(s) == 10:
        return s + " 00:00:00"
    return (s + " 00:00:00")[:19] if s else ""


def _moment_in_closed_range(moment_compact: str, lo: str | None, hi: str | None) -> bool:
    """inclusive; lo/hi — 'YYYY-MM-DD HH:MM:SS' yoki None."""
    k = _moment_cmp_key(moment_compact)
    if not k:
        return False
    if lo and k < _moment_cmp_key(lo):
        return False
    if hi and k > _moment_cmp_key(hi):
        return False
    return True


async def _fetch_agent_documents_paginated(
    entity: str,
    counterparty_id: str,
    *,
    parse_row,
    moment_lo: str | None,
    moment_hi: str | None,
    result_limit: int | None,
    max_api_scan: int = 8000,
    enrich_demand_row: bool = False,
) -> list[dict]:
    """
    entity: 'demand' | 'salesreturn'
    result_limit: None = barcha mos keluvchilar (max_api_scan gacha sahifalar).
    """
    url = f"{MOYSKLAD_API}/entity/{entity}"
    collected: list[dict] = []
    offset = 0
    page = 500
    scanned = 0
    while offset < max_api_scan:
        if result_limit is not None and len(collected) >= result_limit:
            break
        expand = (
            "agent,owner,salesChannel,store,state,positions.assortment,attributes,rate.currency"
            if entity == "demand"
            else "agent,owner,salesChannel,store,state,positions.assortment,rate.currency"
        )
        params = {
            "filter": _agent_filter(counterparty_id),
            "limit": page,
            "offset": offset,
            "order": "moment,desc",
            "expand": expand,
        }
        data = await _get(url, params=params)
        batch = data.get("rows") or []
        if not batch:
            break
        scanned += len(batch)
        parsed: list[tuple[dict, dict]] = []
        for row in batch:
            try:
                p = parse_row(row)
            except Exception as ex:
                logger.debug("parse %s row skip: %s", entity, ex)
                continue
            parsed.append((row, p))

        if enrich_demand_row and entity == "demand" and parsed:
            sem = asyncio.Semaphore(MOYSKLAD_ENRICH_CONCURRENCY)

            async def _enrich_one(r: dict, pp: dict) -> None:
                async with sem:
                    try:
                        await enrich_demand_from_moysklad(r, pp)
                    except Exception as ex:
                        logger.warning("enrich_demand_from_moysklad list row: %s", ex)

            await asyncio.gather(*(_enrich_one(r, p) for r, p in parsed))

        for row, p in parsed:
            if moment_lo or moment_hi:
                if not _moment_in_closed_range(p.get("moment") or "", moment_lo, moment_hi):
                    continue
            collected.append(p)
            if result_limit is not None and len(collected) >= result_limit:
                break
        if result_limit is not None and len(collected) >= result_limit:
            break
        if len(batch) < page:
            break
        offset += page
    return collected


async def fetch_demands_for_counterparty(
    counterparty_id: str,
    *,
    moment_lo: str | None = None,
    moment_hi: str | None = None,
    result_limit: int | None = 30,
    max_api_scan: int = 8000,
) -> list[dict]:
    """Otgruzkalar — MoySklad, mahalliy DB emas."""
    return await _fetch_agent_documents_paginated(
        "demand",
        counterparty_id,
        parse_row=parse_demand,
        moment_lo=moment_lo,
        moment_hi=moment_hi,
        result_limit=result_limit,
        max_api_scan=max_api_scan,
        enrich_demand_row=True,
    )


async def fetch_salesreturns_for_counterparty(
    counterparty_id: str,
    *,
    moment_lo: str | None = None,
    moment_hi: str | None = None,
    result_limit: int | None = None,
    max_api_scan: int = 8000,
) -> list[dict]:
    """Qaytarishlar — MoySklad."""
    return await _fetch_agent_documents_paginated(
        "salesreturn",
        counterparty_id,
        parse_row=parse_salesreturn,
        moment_lo=moment_lo,
        moment_hi=moment_hi,
        result_limit=result_limit,
        max_api_scan=max_api_scan,
    )


def parse_order(data: dict) -> dict:
    """
    Parse MoySklad customerorder response into a clean dict.

    Документ может быть оформлен в любой валюте; конвертируем в валюту
    по умолчанию аккаунта через rate.value (см. _to_default_amount).
    """
    agent = data.get("agent", {}) or {}
    agent_phone = agent.get("phone", "") or ""
    owner = data.get("owner") or {}
    owner_name = _person_name(owner)
    warehouse_name = _embedded_name(data.get("store") or {})
    rate = data.get("rate")

    pos_block = data.get("positions") or {}
    rows = pos_block.get("rows", []) if isinstance(pos_block, dict) else []
    items = []
    for pos in rows:
        assortment = pos.get("assortment", {}) or {}
        qty = pos.get("quantity", 0) or 0
        # Двойная картина: price/total остаются в валюте по умолчанию
        # (USD) — для совместимости с базой и старыми вызовами,
        # price_original/total_original в валюте документа — для отображения.
        price = _to_default_amount(pos.get("price"), rate)
        total = round(qty * price, 2)
        price_original = _to_original_amount(pos.get("price"))
        total_original = round(qty * price_original, 2)
        unit_name = (assortment.get("uom") or {}).get("name") or ""
        items.append({
            "name": assortment.get("name", "—"),
            "code": (assortment.get("article") or assortment.get("code") or "").strip(),
            "quantity": qty,
            "uom": unit_name,
            "price": price,
            "total": total,
            "price_original": price_original,
            "total_original": total_original,
        })

    total_sum = _to_default_amount(data.get("sum"), rate)
    total_sum_original = _to_original_amount(data.get("sum"))
    currency_name = _doc_currency_name(rate)

    return {
        "moysklad_id": data.get("id", ""),
        "order_number": data.get("name", ""),
        "moment": _moment_compact_storage(data.get("moment")),
        "status": _state_name(data),
        "agent_name": agent.get("name", ""),
        "agent_phone": agent_phone,
        "agent_href": agent.get("meta", {}).get("href", ""),
        "agent_id": _extract_id(agent.get("meta", {}).get("href", "")),
        "total_usd": total_sum,
        "total_original": total_sum_original,
        "currency": currency_name,
        "items": items,
        "owner_name": owner_name,
        "warehouse_name": warehouse_name,
    }


def _embedded_name(obj: dict | None) -> str:
    if not obj:
        return ""
    return (obj.get("name") or "").strip()


def _person_name(obj: dict | None) -> str:
    """Сотрудник / контрагент — имя из name или ФИО из полей API."""
    if not obj or not isinstance(obj, dict):
        return ""
    n = (obj.get("name") or "").strip()
    if n:
        return n
    fn = (obj.get("firstName") or "").strip()
    ln = (obj.get("lastName") or "").strip()
    mi = (obj.get("middleName") or "").strip()
    parts = " ".join(p for p in (fn, mi, ln) if p).strip()
    if parts:
        return parts
    return (obj.get("shortFio") or obj.get("email") or "").strip()


def _attribute_value_display(attr: dict) -> str:
    """Доп. поле demand — человекочитаемое значение (строка / сотрудник / ссылка)."""
    val = attr.get("value")
    if val is None:
        return ""
    if isinstance(val, dict):
        name = (val.get("name") or "").strip()
        if name:
            return name
        return _embedded_name(val)
    if isinstance(val, bool):
        return ""
    return str(val).strip()


def _seller_attribute_label_keys() -> tuple[str, ...]:
    return (
        "продавец",
        "sotuvchi",
        "сотув",
        "сотувчи",
        "seller",
        "vendor",
        "менеджер",
        "manager",
        "ответственн",
        "javobgar",
        "консульт",
        "consultant",
        "торгов",
    )


def _employee_href_from_attribute(attr: dict) -> str | None:
    """Доп. поле (employee): meta.type=employee и href на сущность employee."""
    val = attr.get("value")
    if not isinstance(val, dict):
        return None
    meta = val.get("meta") or {}
    if (meta.get("type") or "").lower() != "employee":
        return None
    href = (meta.get("href") or "").strip()
    return href or None


def _first_employee_attribute_value(attrs: list) -> str:
    """Первое доп. поле типа employee с непустым отображаемым значением."""
    if not isinstance(attrs, list):
        return ""
    for a in attrs:
        if not isinstance(a, dict):
            continue
        if (a.get("type") or "").lower() != "employee":
            continue
        v = _attribute_value_display(a)
        if v:
            return v
    return ""


def _demand_seller_name(data: dict, owner_name: str) -> str:
    """
    «Продавец» / Sotuvchi: доп. атрибут по названию → тип employee → канал продаж → владелец.
    """
    attrs = data.get("attributes") or []
    if isinstance(attrs, list):
        keys = _seller_attribute_label_keys()
        for a in attrs:
            if not isinstance(a, dict):
                continue
            label = (a.get("name") or "").strip().lower()
            if not label:
                continue
            if any(k in label for k in keys):
                v = _attribute_value_display(a)
                if v:
                    return v
        v2 = _first_employee_attribute_value(attrs)
        if v2:
            return v2
    ch = _embedded_name(data.get("salesChannel"))
    if ch:
        return ch
    return (owner_name or "").strip()


# ── Employee fetch cache ─────────────────────────────────────────────────────
# Bir buyurtmalar ro'yxati yuklanganda har bir demand'ning owner'i bir xil
# bo'lishi mumkin (masalan "Тохир" 50 ta otgruzkani yaratgan). Keshsiz biz
# 50 ta bir xil GET /entity/employee/{id} so'rovini yuboramiz. Agar token
# egasining roli boshqa xodimlarni ko'rishga ruxsat bermasa — 50 ta 403
# javob keladi, bu esa MoySklad'ning rate-limit himoyasini ishga tushiradi
# (429), oqibatda boshqa amallar (manzil saqlash, balans) ham yiqiladi.
#
# Yechim: muvaffaqiyatli javoblarni ham, 403'larni ham keshlaymiz. Bir
# employee uchun ko'pi bilan bitta so'rov yuboriladi (sessiya davomida).
_employee_cache: dict[str, dict | None] = {}
_employee_cache_lock: asyncio.Lock | None = None
_EMPLOYEE_CACHE_MAX = 500


async def _fetch_employee_safe(href: str) -> dict | None:
    """Employee'ni keshdan oladi yoki MoySklad'dan yuklaydi.

    Returns:
        dict — muvaffaqiyatli yuklangan employee
        None — 403 yoki boshqa permanent xato (qayta urinmaymiz)
    """
    global _employee_cache_lock
    if _employee_cache_lock is None:
        _employee_cache_lock = asyncio.Lock()

    async with _employee_cache_lock:
        if href in _employee_cache:
            return _employee_cache[href]

    try:
        emp = await _get(href)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            # Tokenning xodim ma'lumotini ko'rishga ruxsati yo'q —
            # keshga "yo'q" deb qo'yamiz, boshqa demand'lar uchun
            # qayta urinmaymiz.
            async with _employee_cache_lock:
                if len(_employee_cache) < _EMPLOYEE_CACHE_MAX:
                    _employee_cache[href] = None
            logger.warning(
                "Employee fetch forbidden (403) — cached as inaccessible: %s", href,
            )
            return None
        raise
    except Exception as e:
        logger.warning("Employee fetch failed (transient, not cached) %s: %s", href, e)
        return None

    async with _employee_cache_lock:
        if len(_employee_cache) < _EMPLOYEE_CACHE_MAX:
            _employee_cache[href] = emp
    return emp


async def _enrich_seller_from_employee_attributes(raw: dict, shipment: dict) -> None:
    """Если в значении employee только meta — подтянуть ФИО по href (список / PDF)."""
    attrs = raw.get("attributes") or []
    if not isinstance(attrs, list):
        return
    keys = _seller_attribute_label_keys()
    scored: list[tuple[int, dict]] = []
    for a in attrs:
        if not isinstance(a, dict):
            continue
        href = _employee_href_from_attribute(a)
        if not href:
            continue
        label = (a.get("name") or "").strip().lower()
        score = 0
        if label and any(k in label for k in keys):
            score = 2
        elif (a.get("type") or "").lower() == "employee":
            score = 1
        scored.append((score, a))
    scored.sort(key=lambda x: -x[0])
    for _, a in scored:
        href = _employee_href_from_attribute(a)
        if not href:
            continue
        emp = await _fetch_employee_safe(href)
        if emp is None:
            continue
        nm = _person_name(emp)
        if nm:
            shipment["seller_name"] = nm
            return


async def enrich_demand_from_moysklad(raw: dict, shipment: dict) -> None:
    """
    owner в ответе без ФИО (только meta) — подгружаем сотрудника; пересчитываем seller.
    Также: список отгрузок MS возвращает `positions` без rows (только meta-href),
    поэтому если items пуст — дофетчиваем отгрузку целиком.
    """
    owner = raw.get("owner") or {}
    oname = _person_name(owner)
    if not oname:
        href = (owner.get("meta") or {}).get("href")
        if href:
            emp = await _fetch_employee_safe(href)
            if emp is not None:
                oname = _person_name(emp)
                if oname:
                    shipment["owner_name"] = oname
                    raw["owner"] = {**owner, **{k: v for k, v in emp.items() if k != "meta"}}
    elif not (shipment.get("owner_name") or "").strip():
        shipment["owner_name"] = oname

    if not (shipment.get("seller_name") or "").strip():
        shipment["seller_name"] = _demand_seller_name(raw, (shipment.get("owner_name") or oname or "").strip())

    if not (shipment.get("seller_name") or "").strip():
        await _enrich_seller_from_employee_attributes(raw, shipment)

    # Подтягиваем позиции и/или валюту, если в листинговом ответе их не было.
    needs_items = not shipment.get("items")
    needs_currency = not shipment.get("currency") or shipment.get("currency") == "USD" and not (
        ((raw.get("rate") or {}).get("currency") or {}).get("name")
    )
    if needs_items or needs_currency:
        href = (raw.get("meta") or {}).get("href")
        if href:
            try:
                full = await fetch_entity(href)
                full_parsed = parse_demand(full)
                if needs_items and full_parsed.get("items"):
                    shipment["items"] = full_parsed["items"]
                # Перезаписываем валюту/итог из полного объекта — там
                # rate.currency.name гарантированно populated через expand.
                full_currency = full_parsed.get("currency") or "USD"
                shipment["currency"] = full_currency
                if full_parsed.get("total_original") is not None:
                    shipment["total_original"] = full_parsed["total_original"]
            except Exception as e:
                logger.warning("demand items/currency fetch failed for %s: %s", href, e)


def _moment_compact_storage(raw: str | None) -> str:
    """MoySklad moment → DB/ko‘rinish (offset bor bo‘lsa APP_TIMEZONE ga aylantiriladi)."""
    from time_utils import _normalize_moysklad_moment

    compact, rule = _normalize_moysklad_moment(raw)
    if raw and (MS_MOMENT_LOG or logger.isEnabledFor(logging.DEBUG)):
        logger.log(
            logging.INFO if MS_MOMENT_LOG else logging.DEBUG,
            "MoySklad moment raw=%r → stored=%r (%s)",
            raw,
            compact,
            rule,
        )
    return compact


def parse_demand(data: dict) -> dict:
    """Parse MoySklad demand (shipment) response."""
    agent = data.get("agent", {}) or {}
    agent_phone = agent.get("phone", "") or ""
    owner = data.get("owner") or {}
    owner_name = _person_name(owner)
    warehouse_name = _embedded_name(data.get("store") or {})
    rate = data.get("rate")

    pos_block = data.get("positions") or {}
    rows = pos_block.get("rows", []) if isinstance(pos_block, dict) else []
    items = []
    for pos in rows:
        assortment = pos.get("assortment", {}) or {}
        qty = pos.get("quantity", 0) or 0
        # Двойная картина: price/total остаются в валюте по умолчанию
        # (USD) — для совместимости с базой и старыми вызовами,
        # price_original/total_original в валюте документа — для отображения.
        price = _to_default_amount(pos.get("price"), rate)
        total = round(qty * price, 2)
        price_original = _to_original_amount(pos.get("price"))
        total_original = round(qty * price_original, 2)
        unit_name = (assortment.get("uom") or {}).get("name") or ""
        items.append({
            "name": assortment.get("name", "—"),
            "code": (assortment.get("article") or assortment.get("code") or "").strip(),
            "quantity": qty,
            "uom": unit_name,
            "price": price,
            "total": total,
            "price_original": price_original,
            "total_original": total_original,
        })

    total_sum = _to_default_amount(data.get("sum"), rate)
    total_sum_original = _to_original_amount(data.get("sum"))
    currency_name = _doc_currency_name(rate)

    seller_name = _demand_seller_name(data, owner_name)

    return {
        "moysklad_id": data.get("id", ""),
        "shipment_number": data.get("name", ""),
        "moment": _moment_compact_storage(data.get("moment")),
        "status": _state_name(data),
        "agent_name": agent.get("name", ""),
        "agent_phone": agent_phone,
        "agent_href": agent.get("meta", {}).get("href", ""),
        "agent_id": _extract_id(agent.get("meta", {}).get("href", "")),
        "total_usd": total_sum,
        "total_original": total_sum_original,
        "currency": currency_name,
        "items": items,
        "owner_name": owner_name,
        "seller_name": seller_name,
        "warehouse_name": warehouse_name,
    }


def parse_salesreturn(data: dict) -> dict:
    """Parse MoySklad salesreturn (возврат покупателя) response."""
    agent = data.get("agent", {}) or {}
    agent_phone = agent.get("phone", "") or ""
    owner = data.get("owner") or {}
    owner_name = _person_name(owner)
    warehouse_name = _embedded_name(data.get("store") or {})
    rate = data.get("rate")

    pos_block = data.get("positions") or {}
    rows = pos_block.get("rows", []) if isinstance(pos_block, dict) else []
    items = []
    for pos in rows:
        assortment = pos.get("assortment", {}) or {}
        qty = pos.get("quantity", 0) or 0
        # Двойная картина: price/total остаются в валюте по умолчанию
        # (USD) — для совместимости с базой и старыми вызовами,
        # price_original/total_original в валюте документа — для отображения.
        price = _to_default_amount(pos.get("price"), rate)
        total = round(qty * price, 2)
        price_original = _to_original_amount(pos.get("price"))
        total_original = round(qty * price_original, 2)
        unit_name = (assortment.get("uom") or {}).get("name") or ""
        items.append({
            "name": assortment.get("name", "—"),
            "code": (assortment.get("article") or assortment.get("code") or "").strip(),
            "quantity": qty,
            "uom": unit_name,
            "price": price,
            "total": total,
            "price_original": price_original,
            "total_original": total_original,
        })

    total_sum = _to_default_amount(data.get("sum"), rate)
    total_sum_original = _to_original_amount(data.get("sum"))
    currency_name = _doc_currency_name(rate)

    return {
        "moysklad_id": data.get("id", ""),
        "return_number": data.get("name", ""),
        "moment": _moment_compact_storage(data.get("moment")),
        "status": _state_name(data),
        "agent_name": agent.get("name", ""),
        "agent_phone": agent_phone,
        "agent_href": agent.get("meta", {}).get("href", ""),
        "agent_id": _extract_id(agent.get("meta", {}).get("href", "")),
        "total_usd": total_sum,
        "total_original": total_sum_original,
        "currency": currency_name,
        "items": items,
        "owner_name": owner_name,
        "warehouse_name": warehouse_name,
    }


def parse_supply(data: dict) -> dict:
    """Parse MoySklad supply (приёмка) response.

    `agent` — поставщик. Структура совпадает с demand/salesreturn,
    в качестве идентификатора документа используем supply_number.
    """
    agent = data.get("agent", {}) or {}
    agent_phone = agent.get("phone", "") or ""
    owner = data.get("owner") or {}
    owner_name = _person_name(owner)
    warehouse_name = _embedded_name(data.get("store") or {})
    rate = data.get("rate")

    pos_block = data.get("positions") or {}
    rows = pos_block.get("rows", []) if isinstance(pos_block, dict) else []
    items = []
    for pos in rows:
        assortment = pos.get("assortment", {}) or {}
        qty = pos.get("quantity", 0) or 0
        # Двойная картина: price/total остаются в валюте по умолчанию
        # (USD) — для совместимости с базой и старыми вызовами,
        # price_original/total_original в валюте документа — для отображения.
        price = _to_default_amount(pos.get("price"), rate)
        total = round(qty * price, 2)
        price_original = _to_original_amount(pos.get("price"))
        total_original = round(qty * price_original, 2)
        unit_name = (assortment.get("uom") or {}).get("name") or ""
        items.append({
            "name": assortment.get("name", "—"),
            "code": (assortment.get("article") or assortment.get("code") or "").strip(),
            "quantity": qty,
            "uom": unit_name,
            "price": price,
            "total": total,
            "price_original": price_original,
            "total_original": total_original,
        })

    total_sum = _to_default_amount(data.get("sum"), rate)
    total_sum_original = _to_original_amount(data.get("sum"))
    currency_name = _doc_currency_name(rate)

    return {
        "moysklad_id": data.get("id", ""),
        "supply_number": data.get("name", ""),
        "moment": _moment_compact_storage(data.get("moment")),
        "status": _state_name(data),
        "agent_name": agent.get("name", ""),
        "agent_phone": agent_phone,
        "agent_href": agent.get("meta", {}).get("href", ""),
        "agent_id": _extract_id(agent.get("meta", {}).get("href", "")),
        "total_usd": total_sum,
        "total_original": total_sum_original,
        "currency": currency_name,
        "items": items,
        "owner_name": owner_name,
        "warehouse_name": warehouse_name,
    }


def parse_purchasereturn(data: dict) -> dict:
    """Parse MoySklad purchasereturn (возврат поставщику) response."""
    agent = data.get("agent", {}) or {}
    agent_phone = agent.get("phone", "") or ""
    owner = data.get("owner") or {}
    owner_name = _person_name(owner)
    warehouse_name = _embedded_name(data.get("store") or {})
    rate = data.get("rate")

    pos_block = data.get("positions") or {}
    rows = pos_block.get("rows", []) if isinstance(pos_block, dict) else []
    items = []
    for pos in rows:
        assortment = pos.get("assortment", {}) or {}
        qty = pos.get("quantity", 0) or 0
        # Двойная картина: price/total остаются в валюте по умолчанию
        # (USD) — для совместимости с базой и старыми вызовами,
        # price_original/total_original в валюте документа — для отображения.
        price = _to_default_amount(pos.get("price"), rate)
        total = round(qty * price, 2)
        price_original = _to_original_amount(pos.get("price"))
        total_original = round(qty * price_original, 2)
        unit_name = (assortment.get("uom") or {}).get("name") or ""
        items.append({
            "name": assortment.get("name", "—"),
            "code": (assortment.get("article") or assortment.get("code") or "").strip(),
            "quantity": qty,
            "uom": unit_name,
            "price": price,
            "total": total,
            "price_original": price_original,
            "total_original": total_original,
        })

    total_sum = _to_default_amount(data.get("sum"), rate)
    total_sum_original = _to_original_amount(data.get("sum"))
    currency_name = _doc_currency_name(rate)

    return {
        "moysklad_id": data.get("id", ""),
        "return_number": data.get("name", ""),
        "moment": _moment_compact_storage(data.get("moment")),
        "status": _state_name(data),
        "agent_name": agent.get("name", ""),
        "agent_phone": agent_phone,
        "agent_href": agent.get("meta", {}).get("href", ""),
        "agent_id": _extract_id(agent.get("meta", {}).get("href", "")),
        "total_usd": total_sum,
        "total_original": total_sum_original,
        "currency": currency_name,
        "items": items,
        "owner_name": owner_name,
        "warehouse_name": warehouse_name,
    }


def _state_name(data: dict) -> str:
    state = data.get("state", {}) or {}
    return state.get("name", "Noma'lum")


def _extract_id(href: str) -> str:
    return href.rstrip("/").split("/")[-1] if href else ""


def format_moment(moment: str) -> str:
    """Buyurtmalar ro'yxati: sana + soat (bot va PDF bilan bir xil)."""
    from formatting import fmt_datetime_display

    return fmt_datetime_display(moment)


# ─── Daily report aggregation ───────────────────────────────────────────────
# MoySklad хранит документы со временем в МСК (Europe/Moscow). Фильтр по
# `moment` принимает наивную строку, без таймзоны, в МСК. Для дневного отчёта
# рамки сначала строятся в Asia/Tashkent, потом переводятся в МСК.

async def aggregate_documents(
    entity_type: str,
    *,
    moment_from_msk: str,
    moment_to_msk: str,
) -> tuple[int, float]:
    """Считать count и сумму (в валюте по умолчанию аккаунта) документов за интервал.

    Документ может быть оформлен в любой валюте (например, в сумах при
    основной USD). MoySklad возвращает поле `sum` в минимальных единицах
    валюты документа, а в `rate.value` — коэффициент пересчёта в валюту по
    умолчанию (`amount_default = amount_doc * rate.value`). Если rate.value
    отсутствует — документ в валюте по умолчанию (множитель 1).

    entity_type: customerorder | demand | retaildemand | paymentin | cashin |
                 paymentout | cashout | supply | purchasereturn | salesreturn
    Возвращает (count, total_default_currency).
    """
    url = f"{MOYSKLAD_API}/entity/{entity_type}"
    flt = f"moment>={moment_from_msk};moment<={moment_to_msk}"
    page = 1000
    offset = 0
    total_count = 0
    total_default = 0.0
    sample_logged = False
    while True:
        params = {"filter": flt, "limit": page, "offset": offset, "order": "moment,asc"}
        try:
            data = await _get(url, params=params)
        except Exception as e:
            logger.error("aggregate_documents %s failed: %s", entity_type, e)
            break
        rows = data.get("rows") or []
        if offset == 0:
            total_count = int(((data.get("meta") or {}).get("size")) or 0)
        if rows and not sample_logged:
            sample = rows[0]
            logger.info(
                "aggregate_documents %s sample: sum=%s rate=%s",
                entity_type, sample.get("sum"), sample.get("rate"),
            )
            sample_logged = True
        for r in rows:
            sum_minor = float(r.get("sum") or 0)
            rate = r.get("rate") or {}
            rate_value = rate.get("value")
            try:
                factor = float(rate_value) if rate_value is not None else 1.0
            except (TypeError, ValueError):
                factor = 1.0
            total_default += (sum_minor / 100.0) * factor
        if len(rows) < page:
            break
        offset += page
        if offset >= 50000:  # safety cap
            logger.warning("aggregate_documents %s hit safety cap", entity_type)
            break
    return total_count, round(total_default, 2)


async def count_new_counterparties(
    *, created_from_msk: str, created_to_msk: str
) -> int:
    """Сколько контрагентов создано в МойСклад за интервал (МСК-границы)."""
    url = f"{MOYSKLAD_API}/entity/counterparty"
    flt = f"created>={created_from_msk};created<={created_to_msk}"
    try:
        data = await _get(url, params={"filter": flt, "limit": 1})
    except Exception as e:
        logger.error("count_new_counterparties failed: %s", e)
        return 0
    return int(((data.get("meta") or {}).get("size")) or 0)
