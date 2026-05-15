"""Main menu handlers: Balance, Orders, Report, Language."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import logging

from html import escape

import database as db
from keyboards import language_kb, main_menu_kb, report_nav_kb, report_period_kb
from locales import t
from moysklad_api import (
    format_moment,
    find_counterparty_id_by_phone,
    fetch_counterparty_balance,
    fetch_demands_for_counterparty,
    fetch_salesreturns_for_counterparty,
)
from time_utils import local_today
from formatting import doc_number_for_template, fmt_quantity, fmt_usd
from pdf_generator import generate_period_report_pdf

logger = logging.getLogger(__name__)

router = Router()
BALANCE_FETCH_TIMEOUT = 8
COUNTERPARTY_SEARCH_TIMEOUT = 6

# ── Все тексты кнопок периодов (uz + ru) для быстрого матча ───────────────

PERIOD_MAP: dict[str, str] = {
    # uz
    "📅 Kunlik": "daily",
    "📅 Haftalik": "weekly",
    "📅 Oylik": "monthly",
    "📅 Chorak": "quarterly",
    "📅 Yillik": "yearly",
    "📋 Barcha": "all",
    # ru
    "📅 Дневной": "daily",
    "📅 Недельный": "weekly",
    "📅 Месячный": "monthly",
    "📅 Квартал": "quarterly",
    "📅 Годовой": "yearly",
    "📋 Все": "all",
}

PERIOD_LABELS: dict[str, dict[str, str]] = {
    "daily":     {"uz": "Kunlik",   "ru": "Дневной"},
    "weekly":    {"uz": "Haftalik", "ru": "Недельный"},
    "monthly":   {"uz": "Oylik",    "ru": "Месячный"},
    "quarterly": {"uz": "Chorak",   "ru": "Квартал"},
    "yearly":    {"uz": "Yillik",   "ru": "Годовой"},
    "all":       {"uz": "Barcha",   "ru": "Все"},
}

# Все возможные тексты кнопки "назад" (uz + ru)
BACK_TEXTS = {"🔙 Orqaga", "🔙 Назад"}

# Все возможные тексты навигационных кнопок
PREV_TEXTS    = {"◀️ O'tkan", "◀️ Предыдущий"}
CURRENT_TEXTS = {"🔄 Hozir",  "🔄 Текущий"}
NEXT_TEXTS    = {"▶️ Keyingi","▶️ Следующий"}

NAV_TEXTS = PREV_TEXTS | CURRENT_TEXTS | NEXT_TEXTS | BACK_TEXTS
MENU_BALANCE_TEXTS = {"💰 Balans", "💰 Баланс"}
MENU_ORDERS_TEXTS = {"🛒 Buyurtmalar", "🛒 Заказы"}
MENU_REPORT_TEXTS = {"📊 Hisobot", "📊 Отчёт"}
MENU_LANG_TEXTS = {"🌐 Til", "🌐 Язык"}

MS_DOCUMENTS_TIMEOUT = 25.0


# ── Guard helper ───────────────────────────────────────────────────────────

async def _get_user_or_warn(message: Message) -> dict | None:
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer(t("not_registered", "uz"))
    return user


async def _resolve_counterparty_id(user: dict) -> str | None:
    """MoySklad konturagent id — faqat users jadvali / telefon bo‘yicha."""
    cp_id = user.get("moysklad_counterparty_id")
    if cp_id:
        return str(cp_id).strip() or None
    phone = (user.get("phone") or "").strip()
    if not phone:
        return None
    try:
        return await asyncio.wait_for(
            find_counterparty_id_by_phone(phone),
            timeout=COUNTERPARTY_SEARCH_TIMEOUT,
        )
    except Exception as e:
        logger.warning("_resolve_counterparty_id: %s", e)
    return None


# ── Balance ────────────────────────────────────────────────────────────────

@router.message(F.text.in_({"💰 Balans", "💰 Баланс"}))
async def handle_balance(message: Message, state: FSMContext) -> None:
    await state.clear()

    user = await _get_user_or_warn(message)
    if not user:
        return
    lang = user["language"]
    phone = user.get("phone") or ""

    cp_id: str | None = user.get("moysklad_counterparty_id")

    # Если ID контрагента нет в БД — ищем по телефону в МойСклад
    if not cp_id:
        if phone:
            try:
                cp_id = await asyncio.wait_for(
                    find_counterparty_id_by_phone(phone),
                    timeout=COUNTERPARTY_SEARCH_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("Balance: counterparty search timeout for user %s", message.from_user.id)
            except Exception as e:
                logger.error("Balance: find_counterparty_id_by_phone error: %s", e)

    # Получаем живой баланс из МойСклад
    if cp_id:
        try:
            balance = await asyncio.wait_for(
                fetch_counterparty_balance(cp_id),
                timeout=BALANCE_FETCH_TIMEOUT,
            )
            # Some stored cp_ids are stale and return empty report rows (balance=0.0).
            # Re-resolve by phone and retry once with the fresh counterparty id.
            if balance == 0.0 and phone:
                fresh_cp_id = await asyncio.wait_for(
                    find_counterparty_id_by_phone(phone),
                    timeout=COUNTERPARTY_SEARCH_TIMEOUT,
                )
                if fresh_cp_id and fresh_cp_id != cp_id:
                    fresh_balance = await asyncio.wait_for(
                        fetch_counterparty_balance(fresh_cp_id),
                        timeout=BALANCE_FETCH_TIMEOUT,
                    )
                    cp_id = fresh_cp_id
                    balance = fresh_balance
                    logger.info(
                        "Balance: relinked stale cp_id for user %s -> %s",
                        message.from_user.id,
                        cp_id,
                    )
        except asyncio.TimeoutError:
            logger.warning("Balance: timeout for user %s (cp=%s)", message.from_user.id, cp_id)
            balance = user.get("balance_usd") or 0.0
        except Exception as e:
            logger.error("Balance: fetch_counterparty_balance error for cp=%s: %s", cp_id, e)
            balance = user.get("balance_usd") or 0.0
        try:
            await db.save_moysklad_counterparty_id(message.from_user.id, cp_id)
        except Exception as e:
            logger.debug("Balance: save_moysklad_counterparty_id: %s", e)
    else:
        logger.warning("Balance: counterparty not found for user %s (phone=%s)", message.from_user.id, user.get("phone"))
        balance = user.get("balance_usd") or 0.0

    await message.answer(
        t("balance", lang, amount=fmt_usd(balance)),
        reply_markup=main_menu_kb(lang),
    )




# ── Orders ─────────────────────────────────────────────────────────────────

@router.message(F.text.in_({"🛒 Buyurtmalar", "🛒 Заказы"}))
async def handle_orders(message: Message, state: FSMContext) -> None:
    await state.clear()

    user = await _get_user_or_warn(message)
    if not user:
        return
    lang = user["language"]

    cp_id = await _resolve_counterparty_id(user)
    if not cp_id:
        await message.answer(t("no_counterparty_for_list", lang), reply_markup=main_menu_kb(lang))
        return

    try:
        shipments = await asyncio.wait_for(
            fetch_demands_for_counterparty(cp_id, result_limit=25),
            timeout=MS_DOCUMENTS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("handle_orders: MoySklad timeout user=%s", message.from_user.id)
        await message.answer(t("orders_ms_error", lang), reply_markup=main_menu_kb(lang))
        return
    except Exception as e:
        logger.exception("handle_orders: MoySklad fetch: %s", e)
        await message.answer(t("orders_ms_error", lang), reply_markup=main_menu_kb(lang))
        return

    if not shipments:
        await message.answer(t("no_shipments", lang), reply_markup=main_menu_kb(lang))
        return

    lines = [t("shipment_list_header", lang)]
    for ship in shipments:
        date_str = format_moment(ship["moment"])
        seller = escape((ship.get("seller_name") or "").strip() or "—")
        status = escape(str(ship.get("status") or "—"))
        lines.append(
            t(
                "shipment_list_item",
                lang,
                number=escape(doc_number_for_template(ship["shipment_number"])),
                date=escape(date_str),
                seller=seller,
                total=fmt_usd(ship["total_usd"]),
                status=status,
            )
        )
    await message.answer("\n\n".join(lines), reply_markup=main_menu_kb(lang))


# ── Report ─────────────────────────────────────────────────────────────────

class ReportStates(StatesGroup):
    choose_period = State()
    navigate      = State()


@router.message(F.text.in_({"📊 Hisobot", "📊 Отчёт"}))
async def handle_report(message: Message, state: FSMContext) -> None:
    await state.clear()  # сброс предыдущего стейта

    user = await _get_user_or_warn(message)
    if not user:
        return
    lang = user["language"]

    await state.set_state(ReportStates.choose_period)
    await state.update_data(lang=lang, offset=0, period=None)
    await message.answer(
        t("report_choose_period", lang),
        reply_markup=report_period_kb(lang),
    )


@router.message(ReportStates.choose_period)
async def handle_period_choice(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang", "uz")
    text = (message.text or "").strip()

    # Allow main-menu buttons to work even when user is inside report FSM.
    if text in MENU_BALANCE_TEXTS:
        await handle_balance(message, state)
        return
    if text in MENU_ORDERS_TEXTS:
        await handle_orders(message, state)
        return
    if text in MENU_LANG_TEXTS:
        await handle_language(message, state)
        return
    if text in MENU_REPORT_TEXTS:
        await handle_report(message, state)
        return

    # ── Назад → главное меню ──
    if text in BACK_TEXTS:
        await state.clear()
        await message.answer(t("main_menu", lang), reply_markup=main_menu_kb(lang))
        return

    # ── Выбор периода ──
    period = PERIOD_MAP.get(text)
    if not period:
        # Неизвестная кнопка — напомнить что нажать
        await message.answer(
            t("report_choose_period", lang),
            reply_markup=report_period_kb(lang),
        )
        return

    await state.update_data(period=period, offset=0)
    await state.set_state(ReportStates.navigate)
    await _send_report(message, state)


@router.message(ReportStates.navigate)
async def handle_report_nav(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang   = data.get("lang", "uz")
    offset = data.get("offset", 0)
    text   = (message.text or "").strip()

    # Allow main-menu buttons to work even when user is inside report FSM.
    if text in MENU_BALANCE_TEXTS:
        await handle_balance(message, state)
        return
    if text in MENU_ORDERS_TEXTS:
        await handle_orders(message, state)
        return
    if text in MENU_LANG_TEXTS:
        await handle_language(message, state)
        return
    if text in MENU_REPORT_TEXTS:
        await handle_report(message, state)
        return

    # ── Назад → выбор периода ──
    if text in BACK_TEXTS:
        await state.set_state(ReportStates.choose_period)
        await state.update_data(offset=0)
        await message.answer(
            t("report_choose_period", lang),
            reply_markup=report_period_kb(lang),
        )
        return

    # ── Навигация ──
    if text in PREV_TEXTS:
        await state.update_data(offset=offset + 1)
    elif text in CURRENT_TEXTS:
        await state.update_data(offset=0)
    elif text in NEXT_TEXTS:
        await state.update_data(offset=max(0, offset - 1))
    else:
        # Неизвестный текст (например, пользователь ввёл произвольное сообщение)
        # Просто перерисовываем отчёт без изменения offset
        pass

    await _send_report(message, state)


def _aggregate_items(shipments: list[dict]) -> list[dict]:
    """Объединить позиции по названию через все отгрузки периода.

    Возвращает список {name, quantity, uom, total}, отсортированный по total убыв.
    Цена за единицу не агрегируется — она может отличаться между отгрузками.
    """
    agg: dict[str, dict] = {}
    for s in shipments:
        for it in s.get("items") or []:
            name = (str(it.get("name") or "—").strip()) or "—"
            row = agg.setdefault(
                name, {"name": name, "quantity": 0.0, "total": 0.0, "uom": ""}
            )
            try:
                row["quantity"] += float(it.get("quantity") or 0)
                row["total"] += float(it.get("total") or 0)
            except (TypeError, ValueError):
                pass
            if not row["uom"]:
                u = (str(it.get("uom") or "")).strip()
                if u:
                    row["uom"] = u
    return sorted(agg.values(), key=lambda r: r["total"], reverse=True)


def _format_aggregated_items(
    items: list[dict], lang: str = "uz", max_items: int = 50
) -> str:
    if not items:
        return ""
    default_unit = "шт" if lang == "ru" else "dona"
    head = items[:max_items]
    lines: list[str] = []
    for i, it in enumerate(head, 1):
        unit = escape((it.get("uom") or "").strip() or default_unit)
        qty = fmt_quantity(float(it["quantity"]))
        tot = fmt_usd(float(it["total"]))
        nm = escape(str(it["name"]))
        lines.append(f"#{i}. <b>{nm}</b> — {qty} {unit} (<b>{tot}</b> USD)")
    rest = len(items) - len(head)
    if rest > 0:
        more = (
            f"…и ещё {rest} товаров" if lang == "ru" else f"…yana {rest} ta mahsulot"
        )
        lines.append(more)
    return "\n".join(lines)


def _format_per_shipment(
    shipments: list[dict],
    returns: list[dict],
    lang: str,
    *,
    max_chars: int = 3500,
) -> str:
    """Invoice-style текст: для каждой отгрузки/возврата заголовок, позиции и сумма чека.

    Если общая длина блока превышает max_chars, обрезаем и добавляем
    «…и ещё N документов».
    """
    is_uz = (lang or "uz").lower().startswith("uz")
    ship_label   = "📦 Otgruzka"   if is_uz else "📦 Отгрузка"
    ret_label    = "🔄 Qaytarish"  if is_uz else "🔄 Возврат"
    from_word    = "dan"           if is_uz else "от"
    check_total  = "Chek summasi"  if is_uz else "Сумма чека"
    no_items_lbl = "(pozitsiyalar yo'q)" if is_uz else "(позиций нет)"
    truncated_t  = "…va boshqa {n} ta hujjat" if is_uz else "…и ещё {n} документов"
    default_unit = "dona"          if is_uz else "шт"

    docs: list[tuple[dict, str, str]] = []
    docs.extend((s, ship_label, "shipment_number") for s in shipments)
    docs.extend((r, ret_label, "return_number") for r in returns)

    rendered: list[str] = []
    accumulated = 0
    for i, (d, label, num_field) in enumerate(docs):
        moment = (d.get("moment") or "")[:10]
        try:
            y, mo, dd = moment.split("-")
            date_disp = f"{dd}.{mo}.{y}"
        except ValueError:
            date_disp = moment
        num = d.get(num_field) or ""
        total_orig = float(d.get("total_original") or 0)
        currency = (d.get("currency") or "USD").strip()

        block_lines: list[str] = []
        title = f"<b>{label} №{escape(str(num))}</b>"
        if date_disp:
            title += f" {from_word} {date_disp}"
        block_lines.append(title)

        items = d.get("items") or []
        if items:
            for j, it in enumerate(items, 1):
                qty = fmt_quantity(float(it.get("quantity") or 0))
                unit = escape((it.get("uom") or "").strip() or default_unit)
                price = fmt_usd(float(it.get("price_original") or 0))
                tot = fmt_usd(float(it.get("total_original") or 0))
                name = escape(str(it.get("name") or "—"))
                cur = escape(currency)
                block_lines.append(
                    f"  {j}. {name} — {qty} {unit} × {price} = <b>{tot} {cur}</b>"
                )
        else:
            block_lines.append(f"  {no_items_lbl}")

        block_lines.append(
            f"<b>{check_total}: {fmt_usd(total_orig)} {escape(currency)}</b>"
        )
        block = "\n".join(block_lines)

        if accumulated + len(block) + 2 > max_chars and rendered:
            remaining = len(docs) - i
            rendered.append(truncated_t.format(n=remaining))
            break
        rendered.append(block)
        accumulated += len(block) + 2

    return "\n\n".join(rendered)


async def _send_report(message: Message, state: FSMContext) -> None:
    data   = await state.get_data()
    lang   = data.get("lang", "uz")
    period = data.get("period", "monthly")
    offset = data.get("offset", 0)

    date_from, date_to = _get_period_bounds(period, offset)
    iso_from = date_from.isoformat()
    iso_to   = date_to.isoformat()
    uid      = message.from_user.id
    nav_kb   = report_nav_kb(lang)

    urow = await db.get_user(uid)
    cp_id = await _resolve_counterparty_id(urow or {})
    if not cp_id:
        await message.answer(t("no_counterparty_for_list", lang), reply_markup=nav_kb)
        return

    moment_lo = f"{iso_from} 00:00:00"
    moment_hi = f"{iso_to} 23:59:59"
    try:
        shipments = await asyncio.wait_for(
            fetch_demands_for_counterparty(
                cp_id,
                moment_lo=moment_lo,
                moment_hi=moment_hi,
                result_limit=None,
                max_api_scan=8000,
            ),
            timeout=MS_DOCUMENTS_TIMEOUT,
        )
        returns = await asyncio.wait_for(
            fetch_salesreturns_for_counterparty(
                cp_id,
                moment_lo=moment_lo,
                moment_hi=moment_hi,
                result_limit=None,
                max_api_scan=8000,
            ),
            timeout=MS_DOCUMENTS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("_send_report: MoySklad timeout user=%s", uid)
        await message.answer(t("orders_ms_error", lang), reply_markup=nav_kb)
        return
    except Exception as e:
        logger.exception("_send_report: MoySklad fetch: %s", e)
        await message.answer(t("orders_ms_error", lang), reply_markup=nav_kb)
        return

    ship_count  = len(shipments)
    ret_count   = len(returns)
    ship_total  = sum(s["total_usd"] for s in shipments)
    ret_total   = sum(r["total_usd"] for r in returns)

    net_total = ship_total - ret_total
    period_label = PERIOD_LABELS.get(period, {}).get(lang, period)

    if ship_count + ret_count == 0:
        await message.answer(t("report_empty", lang), reply_markup=nav_kb)
        return

    items_section = ""
    aggregated_items: list[dict] = _aggregate_items(shipments) if shipments else []
    per_doc_block = _format_per_shipment(shipments, returns, lang)
    if per_doc_block:
        items_section = f"\n\n{per_doc_block}"

    text = t(
        "report_result",
        lang,
        period_label=period_label,
        date_from=date_from.strftime("%d.%m.%Y"),
        date_to=date_to.strftime("%d.%m.%Y"),
        ship_count=ship_count,
        ship_total=fmt_usd(ship_total),
        ret_count=ret_count,
        ret_total=fmt_usd(ret_total),
        total=fmt_usd(net_total),
        items=items_section,
    )
    await message.answer(text, reply_markup=nav_kb)

    # PDF-версия того же отчёта.
    try:
        customer_name = (urow or {}).get("name") or ""
        customer_phone = (urow or {}).get("phone") or ""
        if customer_phone and not customer_phone.startswith("+"):
            customer_phone = "+" + customer_phone

        pdf_bytes = await asyncio.to_thread(
            generate_period_report_pdf,
            lang=lang,
            period_label=period_label,
            date_from=date_from.strftime("%d.%m.%Y"),
            date_to=date_to.strftime("%d.%m.%Y"),
            customer_name=customer_name,
            customer_phone=customer_phone,
            shipments=shipments,
            returns=returns,
            ship_total=ship_total,
            ret_total=ret_total,
            aggregated_items=aggregated_items,
        )
        filename = (
            f"hisobot_{period}_{date_from.strftime('%Y%m%d')}"
            f"-{date_to.strftime('%Y%m%d')}.pdf"
        )
        await message.answer_document(
            BufferedInputFile(pdf_bytes, filename=filename),
        )
    except Exception:
        logger.exception("_send_report: PDF generation/send failed for user=%s", uid)


def _get_period_bounds(period: str, offset: int) -> tuple[date, date]:
    today = local_today()

    if period == "daily":
        d = today - timedelta(days=offset)
        return d, d

    elif period == "weekly":
        # Начало текущей недели (понедельник)
        current_week_start = today - timedelta(days=today.weekday())
        start = current_week_start - timedelta(weeks=offset)
        end   = start + timedelta(days=6)
        return start, end

    elif period == "monthly":
        year  = today.year
        month = today.month - offset
        # Нормализация: уходим в прошлое если month ≤ 0
        while month <= 0:
            month += 12
            year  -= 1
        start = date(year, month, 1)
        # Последний день месяца
        if month == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
        return start, end

    elif period == "quarterly":
        year    = today.year
        current_q = (today.month - 1) // 3  # 0..3
        q = current_q - offset
        while q < 0:
            q    += 4
            year -= 1
        start_month = q * 3 + 1            # 1, 4, 7, 10
        end_month   = start_month + 2      # 3, 6, 9, 12
        start = date(year, start_month, 1)
        if end_month == 12:
            end = date(year, 12, 31)
        else:
            end = date(year, end_month + 1, 1) - timedelta(days=1)
        return start, end

    elif period == "yearly":
        year = today.year - offset
        return date(year, 1, 1), date(year, 12, 31)

    else:  # "all"
        return date(2000, 1, 1), today


# ── Language ───────────────────────────────────────────────────────────────

@router.message(F.text.in_({"🌐 Til", "🌐 Язык"}))
async def handle_language(message: Message, state: FSMContext) -> None:
    await state.clear()

    user = await _get_user_or_warn(message)
    if not user:
        return
    await message.answer(
        t("choose_language", user["language"]),
        reply_markup=language_kb(),
    )


@router.callback_query(F.data.startswith("lang:"))
async def handle_lang_callback(callback: CallbackQuery, state: FSMContext) -> None:
    lang = callback.data.split(":")[1]
    await state.clear()  # сброс FSM-стейта
    await db.set_user_language(callback.from_user.id, lang)

    await callback.message.edit_text(t("language_set", lang))
    await callback.message.answer(
        t("main_menu", lang),
        reply_markup=main_menu_kb(lang),
    )
    await callback.answer()


@router.message()
async def handle_fallback_message(message: Message, state: FSMContext) -> None:
    """Stiker, boshqa matn, tugma matni emas — 'is not handled' o‘rniga menyuni qaytarish."""
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer(t("not_registered", "uz"))
        return
    lang = user.get("language") or "uz"
    await state.clear()
    await message.answer(t("menu_fallback", lang), reply_markup=main_menu_kb(lang))
