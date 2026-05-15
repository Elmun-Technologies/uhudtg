"""Human-readable number and date formatting for bot messages."""


def fmt_usd(value: float) -> str:
    """Format money like 20,000.00 (comma thousands, dot decimals)."""
    return f"{float(value):,.2f}"


def fmt_date_dd_mm_yyyy(moment_compact: str) -> str:
    """
    '2026-03-02 14:30' or '2026-03-02T14:30' → '02.03.2026'
    """
    if not moment_compact:
        return ""
    try:
        date_part = moment_compact.replace("T", " ").split()[0]
        y, m, d = date_part.split("-")
        return f"{d}.{m}.{y}"
    except Exception:
        return moment_compact


def fmt_datetime_display(moment_compact: str) -> str:
    """
    Allaqachon APP_TIMEZONE ga aylantirilgan ixcham qator → '02.03.2026 14:30'.
    Bu yerda **qayta** zona aylantirish qilinmaydi (parse_demand allaqachon qiladi).
    """
    if not moment_compact:
        return ""
    s = str(moment_compact).strip().replace("T", " ")
    if not s:
        return ""
    parts = s.split()
    if not parts:
        return moment_compact
    date_part = parts[0]
    time_hm = ""
    if len(parts) >= 2:
        tp = parts[1]
        bits = tp.split(":")
        if len(bits) >= 2:
            try:
                time_hm = f"{int(bits[0]):02d}:{int(bits[1]):02d}"
            except ValueError:
                time_hm = tp[:5]
        else:
            time_hm = tp[:5]
    try:
        y, mo, d = date_part.split("-")
        out = f"{d}.{mo}.{y}"
        return f"{out} {time_hm}".strip() if time_hm else out
    except Exception:
        return moment_compact


def fmt_quantity(qty: float) -> str:
    """Trim trailing zeros for quantities like 60 or 1.5."""
    if qty == int(qty):
        return str(int(qty))
    s = f"{qty:.4f}".rstrip("0").rstrip(".")
    return s or "0"


def doc_number_for_template(name: str) -> str:
    """MoySklad '08884' → 'N08884' for messages like #N08884."""
    n = (name or "").strip()
    if not n:
        return "—"
    core = n.lstrip("Nn").strip() or n
    return f"N{core}"
