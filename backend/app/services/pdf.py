"""Monthly P&L PDF (reportlab). Amounts are shown as 'Rs' because base PDF fonts have no rupee glyph."""
from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor("#1D2B2A")
GREEN = colors.HexColor("#2E6A57")
MUTED = colors.HexColor("#6A7672")
RULE = colors.HexColor("#D9DDD8")
CHILI = colors.HexColor("#B4372B")

TOTAL_KEYS = {"net_sales", "cogs", "gross_profit", "restaurant_margin", "ebitda"}


def _money(v: float | None) -> str:
    if v is None:
        return "-"
    sign = "-" if v < 0 else ""
    v = abs(v)
    # Indian digit grouping: 12,34,567.00
    whole, frac = f"{v:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}Rs {whole}.{frac}"


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{v:.1f}%"


def pnl_pdf(pnl: dict, outlet_name: str, month_label: str, audit_summary: dict | None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm
    )
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=18, textColor=INK, alignment=0, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], fontSize=9.5, textColor=MUTED, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, textColor=INK, spaceBefore=12, spaceAfter=6)
    note = ParagraphStyle("note", parent=ss["Normal"], fontSize=8.5, textColor=MUTED, leading=11)

    story = [
        Paragraph(f"{outlet_name}: profit and loss", h1),
        Paragraph(
            f"{month_label} &nbsp;|&nbsp; {pnl['days_of_operation']} days of operation &nbsp;|&nbsp; "
            f"generated {datetime.now().strftime('%d %b %Y, %H:%M')}",
            sub,
        ),
    ]

    data = [["", "Amount", "% of net sales"]]
    styles = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 10),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]
    for i, ln in enumerate(pnl["lines"], start=1):
        pct = ln["pct"]
        if ln["key"] in ("gross_sale", "complimentary", "discount"):
            pct_txt = "-" if pct is None else f"{pct:.1f}% of gross"
        else:
            pct_txt = _pct(pct)
        data.append([ln["label"], _money(ln["value"]), pct_txt])
        if ln["key"] in TOTAL_KEYS:
            styles += [
                ("FONT", (0, i), (-1, i), "Helvetica-Bold", 10),
                ("LINEABOVE", (0, i), (-1, i), 0.5, RULE),
            ]
        if ln["key"] == "ebitda":
            styles += [
                ("LINEABOVE", (0, i), (-1, i), 1, INK),
                ("TEXTCOLOR", (1, i), (-1, i), GREEN if ln["value"] >= 0 else CHILI),
            ]
    t = Table(data, colWidths=[85 * mm, 45 * mm, 42 * mm])
    t.setStyle(TableStyle(styles))
    story.append(t)

    r = pnl["ratios"]
    story.append(Paragraph("Cost ratios", h2))
    rt = Table(
        [
            ["Food cost (kitchen stations / net sales)", _pct(r["food_cost_pct"])],
            ["Packaging cost / net sales", _pct(r["packaging_cost_pct"])],
            ["Gross cost (all stations / total gross)", _pct(r["gross_cost_pct"])],
        ],
        colWidths=[130 * mm, 42 * mm],
    )
    rt.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 9.5),
                ("TEXTCOLOR", (0, 0), (-1, -1), INK),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.3, RULE),
            ]
        )
    )
    story.append(rt)

    story.append(Paragraph("Consumption by station", h2))
    st = [["Station", "Cost", "% of net sales"]]
    net = next(ln["value"] for ln in pnl["lines"] if ln["key"] == "net_sales")
    for s in pnl["stations"]:
        st.append([s["name"], _money(s["cost"]), _pct(s["cost"] / net * 100 if net else None)])
    stt = Table(st, colWidths=[85 * mm, 45 * mm, 42 * mm])
    stt.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 9.5),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("LINEBELOW", (0, 1), (-1, -2), 0.3, RULE),
            ]
        )
    )
    story.append(stt)

    if audit_summary:
        story.append(Paragraph("Month-end stock audit", h2))
        at = Table(
            [
                ["Items counted", str(audit_summary["items_counted"])],
                ["Items over variance threshold", str(audit_summary["items_flagged"])],
                ["Shortage value", _money(audit_summary["shortage_value"])],
                ["Excess value", _money(audit_summary["excess_value"])],
                ["Closing stock value", _money(audit_summary["closing_stock_value"])],
            ],
            colWidths=[130 * mm, 42 * mm],
        )
        at.setStyle(
            TableStyle(
                [
                    ("FONT", (0, 0), (-1, -1), "Helvetica", 9.5),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("LINEBELOW", (0, 0), (-1, -2), 0.3, RULE),
                ]
            )
        )
        story.append(at)

    story.append(Spacer(1, 10))
    notes = []
    if not pnl["wage_cost_entered"]:
        notes.append("Wage cost has not been entered for this month, so margin and EBITDA exclude wages.")
    notes.append(
"COGS = raw-material consumption cost + cooked-food wastage. "
        "Audit variance % = (expected - counted) / expected stock."
    )
    for n in notes:
        story.append(Paragraph(n, note))
    doc.build(story)
    return buf.getvalue()
