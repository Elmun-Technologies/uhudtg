"""
aiohttp server that receives MoySklad webhooks and dispatches Telegram notifications.

МойСклад → POST /moysklad/webhook
  • customerorder CREATE  → send order notification to customer
  • demand        CREATE  → generate PDF + send to customer
  • cashin/paymentin CREATE → send payment notification to customer

История отгрузок/заказов/возвратов в SQLite не хранится — списки и отчёт
читаются из МойСклад API. В users сохраняются только привязка к контрагенту и баланс.
"""

import logging
import asyncio
from html import escape
from aiohttp import web
from aiogram.types import BufferedInputFile

import database as db
import moysklad_api as ms
from config import WEBHOOK_PATH, WEBHOOK_SECRET, WEBHOOK_WORKERS
from pdf_generator import generate_shipment_pdf
from formatting import doc_number_for_template, fmt_datetime_display, fmt_quantity, fmt_usd

logger = logging.getLogger(__name__)

_bot = None
_webhook_queue = None
WEBHOOK_QUEUE_MAXSIZE = 500


def setup(app: web.Application, bot) -> None:
    global _bot
    _bot = bot
    app.router.add_post(WEBHOOK_PATH, handle_moysklad_webhook)
    app.cleanup_ctx.append(_webhook_worker_context)


async def _webhook_worker_context(app: web.Application):
    global _webhook_queue
    _webhook_queue = asyncio.Queue(maxsize=WEBHOOK_QUEUE_MAXSIZE)
    workers = [asyncio.create_task(_webhook_worker(i + 1)) for i in range(WEBHOOK_WORKERS)]
    logger.info("Webhook workers started: %d", WEBHOOK_WORKERS)
    try:
        yield
    finally:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        logger.info("Webhook workers stopped")


async def _webhook_worker(worker_id: int) -> None:
    while True:
        event = await _webhook_queue.get()
        try:
            await _dispatch_event(event["entity_type"], event["action"], event["href"])
        except Exception as exc:
            logger.exception(
                "Webhook worker #%s error [%s %s]: %s",
                worker_id,
                event.get("entity_type"),
                event.get("action"),
                exc,
            )
        finally:
            _webhook_queue.task_done()


async def _dispatch_event(entity_type: str, action: str, href: str) -> None:
    if entity_type == "customerorder" and action == "CREATE":
        await _process_order(href)
    elif entity_type == "demand" and action == "CREATE":
        await _process_shipment(href)
    elif entity_type == "salesreturn" and action == "CREATE":
        await _process_salesreturn(href)
    elif entity_type in ("cashin", "paymentin", "cashout", "paymentout") and action == "CREATE":
        await _process_payment(href, entity_type)
    elif entity_type == "supply" and action == "CREATE":
        await _process_supply(href)
    elif entity_type == "purchasereturn" and action == "CREATE":
        await _process_purchasereturn(href)


async def handle_moysklad_webhook(request: web.Request) -> web.Response:
    secret = request.rel_url.query.get("secret") or request.headers.get("X-Webhook-Secret", "")
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        logger.warning("Webhook: invalid secret from %s", request.remote)
        return web.Response(status=403)

    try:
        payload = await request.json()
    except Exception:
        return web.Response(status=400)

    events = payload.get("events", [])
    if not isinstance(events, list):
        return web.Response(status=400)

    for event in events:
        meta        = event.get("meta", {})
        entity_type = meta.get("type", "")
        href        = meta.get("href", "")
        action      = event.get("action", "")

        if not href:
            continue

        if _webhook_queue is None:
            try:
                await _dispatch_event(entity_type, action, href)
            except Exception as exc:
                logger.exception("Webhook error [%s %s]: %s", entity_type, action, exc)
            continue

        try:
            _webhook_queue.put_nowait(
                {"entity_type": entity_type, "action": action, "href": href}
            )
        except asyncio.QueueFull:
            logger.warning(
                "Webhook queue is full (%s), processing inline [%s %s]",
                WEBHOOK_QUEUE_MAXSIZE,
                entity_type,
                action,
            )
            try:
                await _dispatch_event(entity_type, action, href)
            except Exception as exc:
                logger.exception("Webhook inline error [%s %s]: %s", entity_type, action, exc)

    return web.Response(text="accepted")


# ─────────────────────────────────────────────────────────────────────────────

async def _process_order(href: str) -> None:
    raw   = await ms.fetch_entity(href)
    order = ms.parse_order(raw)

    user       = await db.get_user_by_phone(order["agent_phone"])
    telegram_id = user["telegram_id"] if user else None
    balance = float(user["balance_usd"]) if user and user.get("balance_usd") is not None else 0.0

    if telegram_id and order["agent_id"]:
        await db.save_moysklad_counterparty_id(telegram_id, order["agent_id"])

    logger.info(
        "Order %s (MoySklad only, DB history not stored), phone=%s",
        order["order_number"],
        order["agent_phone"],
    )


async def _process_shipment(href: str) -> None:
    raw      = await ms.fetch_entity(href)
    shipment = ms.parse_demand(raw)
    await ms.enrich_demand_from_moysklad(raw, shipment)

    user        = await db.get_user_by_phone(shipment["agent_phone"])
    telegram_id = user["telegram_id"] if user else None
    lang        = user["language"]    if user else "uz"

    balance_after = 0.0
    if shipment["agent_id"]:
        try:
            balance_after = await ms.fetch_counterparty_balance(shipment["agent_id"])
        except Exception as e:
            logger.error("Shipment balance fetch failed for cp=%s: %s", shipment["agent_id"], e)

    if telegram_id and shipment["agent_id"]:
        await db.save_moysklad_counterparty_id(telegram_id, shipment["agent_id"])

    balance_before = balance_after + shipment["total_usd"]

    if not telegram_id or not _bot:
        logger.info("Shipment %s saved; no TG user for phone %s",
                    shipment["shipment_number"], shipment["agent_phone"])
        return

    from locales import t

    date_str = fmt_datetime_display(shipment["moment"])
    owner_name = (shipment.get("owner_name") or "").strip() or "—"
    seller_disp = (shipment.get("seller_name") or "").strip() or "—"
    warehouse = (shipment.get("warehouse_name") or "").strip() or "—"
    text = t(
        "shipment_notification", lang,
        number=escape(doc_number_for_template(shipment["shipment_number"])),
        date=escape(date_str),
        created_by=escape(owner_name),
        responsible=escape(owner_name),
        seller=escape(seller_disp),
        name=escape(shipment["agent_name"] or ""),
        phone=escape(shipment["agent_phone"] or ""),
        warehouse=escape(warehouse),
        items=_format_items(shipment["items"], lang),
        total=fmt_usd(shipment["total_usd"]),
        balance=fmt_usd(balance_after),
    )
    await _bot.send_message(telegram_id, text)
    try:
        pdf_bytes = generate_shipment_pdf(
            shipment_number=shipment["shipment_number"],
            moment=date_str,
            status=shipment["status"],
            customer_name=shipment["agent_name"],
            customer_phone=shipment["agent_phone"],
            seller_name=seller_disp,
            items=shipment["items"],
            total_usd=shipment["total_usd"],
            balance_before=balance_before,
            balance_after=balance_after,
        )
        pdf_file = BufferedInputFile(
            pdf_bytes,
            filename=f"Shipment_{shipment['shipment_number']}.pdf",
        )
        await _bot.send_document(telegram_id, document=pdf_file)
    except Exception as e:
        logger.error(
            "Shipment PDF send failed for user %s, shipment %s: %s",
            telegram_id,
            shipment["shipment_number"],
            e,
        )
    logger.info("Shipment notification → user %s, shipment %s, balance %.2f",
                telegram_id, shipment["shipment_number"], balance_after)


async def _process_payment(href: str, payment_type: str) -> None:
    raw     = await ms.fetch_entity(href)
    payment = ms.parse_payment(raw, payment_type)

    user        = await db.get_user_by_phone(payment["agent_phone"])
    telegram_id = user["telegram_id"] if user else None
    lang        = user["language"]    if user else "uz"

    balance = 0.0
    if payment["agent_id"]:
        try:
            balance = await ms.fetch_counterparty_balance(payment["agent_id"])
        except Exception as e:
            logger.error("Payment balance fetch failed for cp=%s: %s", payment["agent_id"], e)

    if telegram_id and payment["agent_id"]:
        await db.save_moysklad_counterparty_id(telegram_id, payment["agent_id"])
        logger.info("Linked cp for user %s (cp=%s), balance from MS only",
                    telegram_id, payment["agent_id"])

    if not telegram_id or not _bot:
        logger.info("Payment %s; no TG user for phone '%s'",
                    payment["payment_number"], payment["agent_phone"])
        return

    from locales import t
    date_str   = fmt_datetime_display(payment["moment"])
    method_str = payment["payment_method_ru"] if lang == "ru" else payment["payment_method_uz"]

    template_key = "payout_notification" if payment.get("direction") == "out" else "payment_notification"
    text = t(
        template_key, lang,
        number=escape(doc_number_for_template(payment["payment_number"])),
        date=escape(date_str),
        amount=fmt_usd(payment["amount"]),
        currency=escape(payment["currency"] or ""),
        method=escape(method_str),
        balance=fmt_usd(balance),
    )
    await _bot.send_message(telegram_id, text)
    logger.info("Payment notification (%s) → user %s, payment %s, balance %.2f",
                payment.get("direction"), telegram_id, payment["payment_number"], balance)


async def _process_salesreturn(href: str) -> None:
    raw = await ms.fetch_entity(href)
    ret = ms.parse_salesreturn(raw)

    user = await db.get_user_by_phone(ret["agent_phone"])
    telegram_id = user["telegram_id"] if user else None
    lang = user["language"] if user else "uz"

    balance_after = 0.0
    if ret["agent_id"]:
        try:
            balance_after = await ms.fetch_counterparty_balance(ret["agent_id"])
        except Exception as e:
            logger.error("Return balance fetch failed for cp=%s: %s", ret["agent_id"], e)

    if telegram_id and ret["agent_id"]:
        await db.save_moysklad_counterparty_id(telegram_id, ret["agent_id"])

    balance_before = balance_after - ret["total_usd"]

    if not telegram_id or not _bot:
        logger.info("Return %s saved; no TG user for phone %s",
                    ret["return_number"], ret["agent_phone"])
        return

    from locales import t
    date_str = fmt_datetime_display(ret["moment"])
    owner_name = (ret.get("owner_name") or "").strip() or "—"
    warehouse = (ret.get("warehouse_name") or "").strip() or "—"
    text = t(
        "return_notification", lang,
        number=escape(doc_number_for_template(ret["return_number"])),
        date=escape(date_str),
        created_by=escape(owner_name),
        responsible=escape(owner_name),
        name=escape(ret["agent_name"] or ""),
        phone=escape(ret["agent_phone"] or ""),
        warehouse=escape(warehouse),
        items=_format_items(ret["items"], lang),
        total=fmt_usd(ret["total_usd"]),
        balance=fmt_usd(balance_after),
    )
    await _bot.send_message(telegram_id, text)
    logger.info("Return notification → user %s, return %s, balance %.2f",
                telegram_id, ret["return_number"], balance_after)


async def _process_supply(href: str) -> None:
    raw = await ms.fetch_entity(href)
    supply = ms.parse_supply(raw)

    user = await db.get_user_by_phone(supply["agent_phone"])
    telegram_id = user["telegram_id"] if user else None
    lang = user["language"] if user else "uz"

    balance_after = 0.0
    if supply["agent_id"]:
        try:
            balance_after = await ms.fetch_counterparty_balance(supply["agent_id"])
        except Exception as e:
            logger.error("Supply balance fetch failed for cp=%s: %s", supply["agent_id"], e)

    if telegram_id and supply["agent_id"]:
        await db.save_moysklad_counterparty_id(telegram_id, supply["agent_id"])

    if not telegram_id or not _bot:
        logger.info("Supply %s saved; no TG user for phone %s",
                    supply["supply_number"], supply["agent_phone"])
        return

    from locales import t

    date_str = fmt_datetime_display(supply["moment"])
    owner_name = (supply.get("owner_name") or "").strip() or "—"
    warehouse = (supply.get("warehouse_name") or "").strip() or "—"
    text = t(
        "supply_notification", lang,
        number=escape(doc_number_for_template(supply["supply_number"])),
        date=escape(date_str),
        created_by=escape(owner_name),
        responsible=escape(owner_name),
        name=escape(supply["agent_name"] or ""),
        phone=escape(supply["agent_phone"] or ""),
        warehouse=escape(warehouse),
        items=_format_items(supply["items"], lang),
        total=fmt_usd(supply["total_usd"]),
        balance=fmt_usd(balance_after),
    )
    await _bot.send_message(telegram_id, text)
    logger.info("Supply notification → user %s, supply %s, balance %.2f",
                telegram_id, supply["supply_number"], balance_after)


async def _process_purchasereturn(href: str) -> None:
    raw = await ms.fetch_entity(href)
    ret = ms.parse_purchasereturn(raw)

    user = await db.get_user_by_phone(ret["agent_phone"])
    telegram_id = user["telegram_id"] if user else None
    lang = user["language"] if user else "uz"

    balance_after = 0.0
    if ret["agent_id"]:
        try:
            balance_after = await ms.fetch_counterparty_balance(ret["agent_id"])
        except Exception as e:
            logger.error("Purchasereturn balance fetch failed for cp=%s: %s", ret["agent_id"], e)

    if telegram_id and ret["agent_id"]:
        await db.save_moysklad_counterparty_id(telegram_id, ret["agent_id"])

    if not telegram_id or not _bot:
        logger.info("Purchasereturn %s saved; no TG user for phone %s",
                    ret["return_number"], ret["agent_phone"])
        return

    from locales import t
    date_str = fmt_datetime_display(ret["moment"])
    owner_name = (ret.get("owner_name") or "").strip() or "—"
    warehouse = (ret.get("warehouse_name") or "").strip() or "—"
    text = t(
        "purchasereturn_notification", lang,
        number=escape(doc_number_for_template(ret["return_number"])),
        date=escape(date_str),
        created_by=escape(owner_name),
        responsible=escape(owner_name),
        name=escape(ret["agent_name"] or ""),
        phone=escape(ret["agent_phone"] or ""),
        warehouse=escape(warehouse),
        items=_format_items(ret["items"], lang),
        total=fmt_usd(ret["total_usd"]),
        balance=fmt_usd(balance_after),
    )
    await _bot.send_message(telegram_id, text)
    logger.info("Purchasereturn notification → user %s, return %s, balance %.2f",
                telegram_id, ret["return_number"], balance_after)


def _format_items(items: list[dict], lang: str = "uz") -> str:
    lines = []
    default_unit = "шт" if lang == "ru" else "dona"
    for i, item in enumerate(items, 1):
        qty_f = float(item["quantity"])
        qty_disp = fmt_quantity(qty_f)
        unit = escape((item.get("uom") or "").strip() or default_unit)
        price = item["price"]
        total = item["total"]
        nm = escape(str(item.get("name") or "—"))
        lines.append(
            f"#{i}. <b>{nm}</b>\n"
            f"({qty_disp} {unit} × <b>{fmt_usd(price)}</b> = <b>{fmt_usd(total)}</b> USD)"
        )
    return "\n".join(lines)
