"""Generate shipment PDF in Comfort Textile style."""

import io
import os
from time_utils import local_now
from xml.sax.saxutils import escape

from config import APP_TIMEZONE
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Brand colours
BRAND_BLUE = colors.HexColor("#1565C0")
BRAND_LIGHT = colors.HexColor("#E3F2FD")
GREY_BG = colors.HexColor("#F5F5F5")
GREY_LINE = colors.HexColor("#BDBDBD")

LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "logo.png")

# Helvetica Kirill/o‘zbek gliflarini chizmaydi — TTF (serverda odatan DejaVu)
_pdf_body_fonts: tuple[str, str] | None = None


def _pdf_unicode_font_names() -> tuple[str, str]:
    global _pdf_body_fonts
    if _pdf_body_fonts is not None:
        return _pdf_body_fonts
    out: tuple[str, str] = ("Helvetica", "Helvetica-Bold")
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        _pdf_body_fonts = out
        return out
    pairs = [
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
        (
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        ),
    ]
    for reg_path, bold_path in pairs:
        if os.path.isfile(reg_path) and os.path.isfile(bold_path):
            try:
                pdfmetrics.registerFont(TTFont("ComfortPdfSans", reg_path))
                pdfmetrics.registerFont(TTFont("ComfortPdfSans-Bold", bold_path))
                out = ("ComfortPdfSans", "ComfortPdfSans-Bold")
            except Exception:
                pass
            break
    _pdf_body_fonts = out
    return out


def _esc(text: str) -> str:
    return escape(str(text or ""), entities={"'": "&apos;", '"': "&quot;"})


def _styles():
    base = getSampleStyleSheet()
    fn, fnb = _pdf_unicode_font_names()
    return {
        "company": ParagraphStyle(
            "company",
            parent=base["Normal"],
            fontSize=15,
            leading=18,
            textColor=BRAND_BLUE,
            fontName=fnb,
            alignment=TA_RIGHT,
            spaceAfter=2,
        ),
        "order_num": ParagraphStyle(
            "order_num",
            parent=base["Normal"],
            fontSize=11,
            leading=14,
            textColor=colors.black,
            fontName=fnb,
            alignment=TA_RIGHT,
            spaceAfter=2,
        ),
        "status": ParagraphStyle(
            "status",
            parent=base["Normal"],
            fontSize=9,
            leading=11,
            textColor=GREY_LINE,
            fontName=fn,
            alignment=TA_RIGHT,
            spaceAfter=0,
        ),
        "meta": ParagraphStyle(
            "meta",
            parent=base["Normal"],
            fontSize=9,
            textColor=colors.black,
            fontName=fn,
        ),
        "meta_bold": ParagraphStyle(
            "meta_bold",
            parent=base["Normal"],
            fontSize=9,
            textColor=colors.black,
            fontName=fnb,
        ),
        "section_title": ParagraphStyle(
            "section_title",
            parent=base["Normal"],
            fontSize=11,
            textColor=BRAND_BLUE,
            fontName=fnb,
            spaceBefore=6,
            spaceAfter=4,
        ),
        "footer": ParagraphStyle(
            "footer",
            parent=base["Normal"],
            fontSize=8,
            textColor=GREY_LINE,
            fontName=fn,
        ),
        "normal": ParagraphStyle(
            "normal_cell",
            parent=base["Normal"],
            fontSize=9,
            fontName=fn,
        ),
        "bold_cell": ParagraphStyle(
            "bold_cell",
            parent=base["Normal"],
            fontSize=9,
            fontName=fnb,
        ),
        "right_cell": ParagraphStyle(
            "right_cell",
            parent=base["Normal"],
            fontSize=9,
            fontName=fnb,
            alignment=TA_RIGHT,
            textColor=BRAND_BLUE,
        ),
    }


def generate_shipment_pdf(
    shipment_number: str,
    moment: str,
    status: str,
    customer_name: str,
    customer_phone: str,
    items: list[dict],
    total_usd: float,
    balance_before: float,
    balance_after: float,
    seller_name: str = "",
) -> bytes:
    """
    Generate a shipment PDF and return it as bytes.

    items: list of {"name": str, "quantity": float, "price": float, "total": float, "uom": str}
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = _styles()
    story = []

    # ── Header: logo (fixed column) + stacked text (nested table — avoids overlap) ─
    logo_col_w = 46 * mm
    text_col_w = max(50 * mm, doc.width - logo_col_w)

    if os.path.exists(LOGO_PATH):
        logo_flow = Image(LOGO_PATH, width=24 * mm, height=24 * mm)
        logo_cell = Table(
            [[logo_flow]],
            colWidths=[logo_col_w - 4 * mm],
            rowHeights=[28 * mm],
        )
        logo_cell.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
    else:
        logo_cell = Paragraph("", styles["normal"])

    header_right_stack = Table(
        [
            [Paragraph(_esc("Comfort Textile"), styles["company"])],
            [Paragraph(_esc(shipment_number), styles["order_num"])],
            [Paragraph("YUBORILDI", styles["status"])],
        ],
        colWidths=[text_col_w],
    )
    header_right_stack.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    header_table = Table(
        [[logo_cell, header_right_stack]],
        colWidths=[logo_col_w, text_col_w],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(header_table)

    # Horizontal rule
    story.append(Table(
        [[""]],
        colWidths=[doc.width],
        rowHeights=[1],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BRAND_BLUE),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, BRAND_BLUE),
        ]),
    ))
    story.append(Spacer(1, 4 * mm))

    # Date + Status row
    story.append(Table(
        [[
            Paragraph(_esc(moment), styles["meta"]),
            Paragraph(f'Holat: <b>{_esc(status)}</b>', styles["meta_bold"]),
        ]],
        colWidths=[doc.width / 2, doc.width / 2],
        style=TableStyle([
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]),
    ))
    story.append(Spacer(1, 4 * mm))

    # ── Customer box ───────────────────────────────────────────────────────
    story.append(Paragraph("Mijoz", styles["section_title"]))
    seller_disp = (seller_name or "").strip() or "—"
    customer_data = [
        [
            Paragraph("Ism:", styles["meta"]),
            Paragraph(f"<b>{_esc(customer_name)}</b>", styles["meta_bold"]),
        ],
        [
            Paragraph("Telefon:", styles["meta"]),
            Paragraph(_esc(customer_phone), styles["meta"]),
        ],
        [
            Paragraph("Sotuvchi:", styles["meta"]),
            Paragraph(f"<b>{_esc(seller_disp)}</b>", styles["meta_bold"]),
        ],
    ]
    customer_table = Table(
        customer_data,
        colWidths=[25 * mm, None],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GREY_BG),
            ("ROUNDEDCORNERS", [4]),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]),
    )
    story.append(customer_table)
    story.append(Spacer(1, 5 * mm))

    # ── Products table ─────────────────────────────────────────────────────
    story.append(Paragraph("Mahsulotlar", styles["section_title"]))

    col_num = 10 * mm
    col_qty = 32 * mm
    col_price = 28 * mm
    col_total = 28 * mm
    col_name = doc.width - col_num - col_qty - col_price - col_total

    fn, fnb = _pdf_unicode_font_names()

    def _hdr(text):
        return Paragraph(f"<b>{text}</b>", ParagraphStyle(
            "hdr", parent=styles["normal"], textColor=colors.white,
            fontName=fnb, fontSize=9,
        ))

    table_data = [[_hdr("№"), _hdr("Nomi"), _hdr("Miqdor"), _hdr("Narx"), _hdr("Jami")]]

    for idx, item in enumerate(items, 1):
        uom = (item.get("uom") or "").strip() or "dona"
        qty_uom = f"{_fmt_qty(item['quantity'])} {uom}"
        table_data.append([
            Paragraph(str(idx), styles["normal"]),
            Paragraph(_esc(item["name"]), styles["normal"]),
            Paragraph(_esc(qty_uom), styles["normal"]),
            Paragraph(_fmt_usd(item["price"]), styles["normal"]),
            Paragraph(_fmt_usd(item["total"]), styles["normal"]),
        ])

    # Total row
    table_data.append([
        "", "",
        Paragraph("<b>Jami</b>", styles["bold_cell"]),
        "",
        Paragraph(f"<b>{_fmt_usd(total_usd)}</b>", styles["right_cell"]),
    ])

    products_table = Table(
        table_data,
        colWidths=[col_num, col_name, col_qty, col_price, col_total],
        repeatRows=1,
    )
    products_table.setStyle(TableStyle([
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), _pdf_unicode_font_names()[1]),
        # Grid
        ("GRID", (0, 0), (-1, -2), 0.3, GREY_LINE),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, GREY_LINE),
        # Padding
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        # Alternating rows
        *[
            ("BACKGROUND", (0, i), (-1, i), GREY_BG)
            for i in range(2, len(table_data) - 1, 2)
        ],
        # Total row
        ("BACKGROUND", (0, -1), (-1, -1), colors.white),
        ("SPAN", (0, -1), (1, -1)),
    ]))
    story.append(products_table)
    story.append(Spacer(1, 5 * mm))

    # ── Balance summary ────────────────────────────────────────────────────
    balance_data = [
        [
            Paragraph("Yuborishdan oldingi balans:", styles["meta"]),
            Paragraph(_fmt_usd(balance_before), styles["meta"]),
        ],
        [
            Paragraph("<b>Yakuniy balans:</b>", styles["meta_bold"]),
            Paragraph(f"<b>{_fmt_usd(balance_after)}</b>", styles["meta_bold"]),
        ],
    ]
    balance_table = Table(
        balance_data,
        colWidths=[None, 35 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GREY_BG),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]),
    )
    story.append(balance_table)

    # ── Footer ─────────────────────────────────────────────────────────────
    story.append(Spacer(1, 8 * mm))
    today = local_now().strftime("%d.%m.%Y %H:%M")
    story.append(Table(
        [[
            Paragraph(
                _esc(f"Hujjat tuzildi: {today} ({APP_TIMEZONE})"),
                styles["footer"],
            ),
            Paragraph("1 / 1", styles["footer"]),
        ]],
        colWidths=[doc.width / 2, doc.width / 2],
        style=TableStyle([
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
        ]),
    ))

    doc.build(story)
    return buffer.getvalue()


def _fmt_usd(value: float) -> str:
    return f"{value:,.2f} USD".replace(",", " ")


def _fmt_money(value: float) -> str:
    """Format number without currency suffix (caller appends label)."""
    return f"{value:,.2f}".replace(",", " ")


def _fmt_qty(value: float) -> str:
    v = float(value)
    if v == int(v):
        return str(int(v))
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s or "0"


def generate_period_report_pdf(
    *,
    lang: str,
    period_label: str,
    date_from: str,
    date_to: str,
    customer_name: str,
    customer_phone: str,
    shipments: list[dict],
    returns: list[dict],
    ship_total: float,
    ret_total: float,
    aggregated_items: list[dict] | None = None,
) -> bytes:
    """Сводный отчёт клиента за период (отгрузки + возвраты + итог + товары)."""
    is_uz = (lang or "uz").lower().startswith("uz")
    L = {
        "title":      ("Hisobot",                  "Отчёт"),
        "period":     ("Davr",                     "Период"),
        "customer":   ("Mijoz",                    "Клиент"),
        "name":       ("Ism",                      "ФИО"),
        "phone":      ("Telefon",                  "Телефон"),
        "summary":    ("Qisqacha xulosa",          "Сводка"),
        "ships_n":    ("Otgruzkalar soni",         "Кол-во отгрузок"),
        "ships_sum":  ("Otgruzkalar jami",         "Сумма отгрузок"),
        "rets_n":     ("Qaytarishlar soni",        "Кол-во возвратов"),
        "rets_sum":   ("Qaytarishlar jami",        "Сумма возвратов"),
        "net":        ("Sof summa (jo‘natma−qaytarish)", "Итого (отгрузки−возвраты)"),
        "ships_h":    ("Otgruzkalar",              "Отгрузки"),
        "rets_h":     ("Qaytarishlar",             "Возвраты"),
        "ship_label": ("Otgruzka",                 "Отгрузка"),
        "ret_label":  ("Qaytarish",                "Возврат"),
        "from":       ("dan",                      "от"),
        "check_total":("Chek summasi",             "Сумма чека"),
        "no_items":   ("Mahsulotlar yo‘q",         "Нет товаров"),
        "col_n":      ("№",                        "№"),
        "col_code":   ("Artikul",                  "Артикул"),
        "col_date":   ("Sana",                     "Дата"),
        "col_doc":    ("Hujjat",                   "Документ"),
        "col_status": ("Holat",                    "Статус"),
        "col_total":  ("Summa",                    "Сумма"),
        "col_name":   ("Nomi",                     "Наименование"),
        "col_qty":    ("Miqdor",                   "Кол-во"),
        "col_uom":    ("Birlik",                   "Ед."),
        "col_price":  ("Narx",                     "Цена"),
        "footer":     ("Comfort Textile",          "Comfort Textile"),
        "empty":      ("(yo‘q)",                   "(нет)"),
        "default_unit": ("dona",                   "шт"),
    }
    def t(key: str) -> str:
        v = L.get(key, (key, key))
        return v[0] if is_uz else v[1]

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    styles = _styles()
    fn, fnb = _pdf_unicode_font_names()
    story = []

    # ── Header: logo + Comfort Textile + period ──────────────────────────
    logo_col_w = 46 * mm
    text_col_w = max(50 * mm, doc.width - logo_col_w)

    if os.path.exists(LOGO_PATH):
        logo_flow = Image(LOGO_PATH, width=24 * mm, height=24 * mm)
        logo_cell = Table(
            [[logo_flow]],
            colWidths=[logo_col_w - 4 * mm],
            rowHeights=[28 * mm],
        )
        logo_cell.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
    else:
        logo_cell = Paragraph("", styles["normal"])

    header_right_stack = Table(
        [
            [Paragraph(_esc("Comfort Textile"), styles["company"])],
            [Paragraph(_esc(f"{t('title')}: {period_label}"), styles["order_num"])],
            [Paragraph(_esc(f"{date_from} — {date_to}"), styles["status"])],
        ],
        colWidths=[text_col_w],
    )
    header_right_stack.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    header_table = Table(
        [[logo_cell, header_right_stack]],
        colWidths=[logo_col_w, text_col_w],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(header_table)

    story.append(Table(
        [[""]],
        colWidths=[doc.width],
        rowHeights=[1],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BRAND_BLUE),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, BRAND_BLUE),
        ]),
    ))
    story.append(Spacer(1, 4 * mm))

    # ── Customer ─────────────────────────────────────────────────────────
    story.append(Paragraph(t("customer"), styles["section_title"]))
    customer_table = Table(
        [
            [
                Paragraph(f"{t('name')}:", styles["meta"]),
                Paragraph(f"<b>{_esc(customer_name)}</b>", styles["meta_bold"]),
            ],
            [
                Paragraph(f"{t('phone')}:", styles["meta"]),
                Paragraph(_esc(customer_phone or "—"), styles["meta"]),
            ],
        ],
        colWidths=[25 * mm, None],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GREY_BG),
            ("ROUNDEDCORNERS", [4]),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]),
    )
    story.append(customer_table)
    story.append(Spacer(1, 5 * mm))

    # ── Summary box ──────────────────────────────────────────────────────
    net_total = round(float(ship_total) - float(ret_total), 2)
    story.append(Paragraph(t("summary"), styles["section_title"]))
    summary_data = [
        [Paragraph(f"{t('ships_n')}:", styles["meta"]),
         Paragraph(f"<b>{len(shipments)}</b>", styles["meta_bold"])],
        [Paragraph(f"{t('ships_sum')}:", styles["meta"]),
         Paragraph(f"<b>{_esc(_fmt_usd(ship_total))}</b>", styles["meta_bold"])],
        [Paragraph(f"{t('rets_n')}:", styles["meta"]),
         Paragraph(f"<b>{len(returns)}</b>", styles["meta_bold"])],
        [Paragraph(f"{t('rets_sum')}:", styles["meta"]),
         Paragraph(f"<b>{_esc(_fmt_usd(ret_total))}</b>", styles["meta_bold"])],
        [Paragraph(f"<b>{t('net')}:</b>", styles["meta_bold"]),
         Paragraph(f"<b>{_esc(_fmt_usd(net_total))}</b>",
                   ParagraphStyle("net", parent=styles["bold_cell"], textColor=BRAND_BLUE))],
    ]
    summary_table = Table(
        summary_data,
        colWidths=[60 * mm, None],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -2), GREY_BG),
            ("BACKGROUND", (0, -1), (-1, -1), BRAND_LIGHT),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("LINEABOVE", (0, -1), (-1, -1), 0.5, BRAND_BLUE),
        ]),
    )
    story.append(summary_table)
    story.append(Spacer(1, 6 * mm))

    # ── Per-shipment / per-return detailed sections ─────────────────────
    def _hdr_cell(text: str):
        return Paragraph(f"<b>{_esc(text)}</b>", ParagraphStyle(
            "items_hdr", parent=styles["normal"], textColor=colors.white,
            fontName=fnb, fontSize=9,
        ))

    def _doc_section(doc_label: str, doc_number: str, moment: str,
                     items: list[dict], doc_total: float, currency: str) -> None:
        # Заголовок: "Отгрузка №10911 от 30.04.2026"
        date_only = (moment or "")[:10]
        try:
            y, m, d = date_only.split("-")
            date_disp = f"{d}.{m}.{y}"
        except ValueError:
            date_disp = date_only or ""
        title = (
            f"{doc_label} № {doc_number}"
            + (f" {t('from')} {date_disp}" if date_disp else "")
        )
        story.append(Paragraph(_esc(title), ParagraphStyle(
            "doc_title", parent=styles["section_title"],
            alignment=1,  # CENTER
            spaceBefore=4, spaceAfter=3,
        )))

        col_n     = 9  * mm
        col_qty   = 20 * mm
        col_uom   = 14 * mm
        col_price = 26 * mm
        col_total = 28 * mm
        col_name  = doc.width - col_n - col_qty - col_uom - col_price - col_total

        cur_label = (currency or "").strip() or "USD"

        head = [[
            _hdr_cell(t("col_n")),
            _hdr_cell(t("col_name")),
            _hdr_cell(t("col_qty")),
            _hdr_cell(t("col_uom")),
            _hdr_cell(f"{t('col_price')}, {cur_label}"),
            _hdr_cell(f"{t('col_total')}, {cur_label}"),
        ]]
        body = []
        for idx, it in enumerate(items, 1):
            body.append([
                Paragraph(str(idx), styles["normal"]),
                Paragraph(_esc(str(it.get("name") or "—")), styles["normal"]),
                Paragraph(_esc(_fmt_qty(it.get("quantity", 0))), styles["normal"]),
                Paragraph(_esc(str(it.get("uom") or "")), styles["normal"]),
                Paragraph(_esc(_fmt_money(float(it.get("price_original") or 0))), styles["right_cell"]),
                Paragraph(_esc(_fmt_money(float(it.get("total_original") or 0))), styles["right_cell"]),
            ])
        if not body:
            body.append([
                Paragraph(_esc(t("no_items")), styles["normal"]),
            ] + [Paragraph("", styles["normal"]) for _ in range(5)])

        tbl = Table(
            head + body,
            colWidths=[col_n, col_name, col_qty, col_uom, col_price, col_total],
            repeatRows=1,
        )
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY_BG]),
            ("FONTNAME", (0, 0), (-1, -1), fn),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, GREY_LINE),
        ]))
        story.append(tbl)

        # Сумма чека (под таблицей справа) — в валюте документа
        total_row = Table(
            [[
                Paragraph(f"<b>{_esc(t('check_total'))}:</b>", styles["meta_bold"]),
                Paragraph(
                    f"<b>{_esc(_fmt_money(float(doc_total or 0)))} {_esc(cur_label)}</b>",
                    ParagraphStyle("ct", parent=styles["bold_cell"],
                                   textColor=BRAND_BLUE, alignment=2),
                ),
            ]],
            colWidths=[doc.width - 50 * mm, 50 * mm],
        )
        total_row.setStyle(TableStyle([
            ("ALIGN", (0, 0), (0, 0), "RIGHT"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(total_row)
        story.append(Spacer(1, 5 * mm))

    if shipments:
        for s in shipments:
            _doc_section(
                doc_label=t("ship_label"),
                doc_number=str(s.get("shipment_number") or ""),
                moment=s.get("moment") or "",
                items=s.get("items") or [],
                doc_total=float(s.get("total_original") or 0),
                currency=s.get("currency") or "USD",
            )

    if returns:
        for r in returns:
            _doc_section(
                doc_label=t("ret_label"),
                doc_number=str(r.get("return_number") or ""),
                moment=r.get("moment") or "",
                items=r.get("items") or [],
                doc_total=float(r.get("total_original") or 0),
                currency=r.get("currency") or "USD",
            )

    # ── Footer ───────────────────────────────────────────────────────────
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        f"{t('footer')} • {local_now().strftime('%d.%m.%Y %H:%M')}",
        styles["footer"],
    ))

    doc.build(story)
    return buffer.getvalue()
