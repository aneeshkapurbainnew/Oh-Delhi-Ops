import calendar
from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import outlet_id
from ..db import get_db
from ..models import Audit, Item
from ..services.pdf import pnl_pdf
from ..services.pnl import daily_series, monthly_pnl, review_counts
from ..services.pricing import PriceBook, month_bounds
from ..services.stock import compute_audit_chain, month_end_summary, stock_levels
from .daily import pending_rows
from .purchases import outstanding_by_vendor
from .setup import get_settings_

router = APIRouter(prefix="/reports", tags=["reports"])


def _label(month: str) -> str:
    y, m = month.split("-")
    return f"{calendar.month_name[int(m)]} {y}"


@router.get("/pnl")
def pnl(month: str, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    return monthly_pnl(db, oid, month)


@router.get("/pnl.pdf")
def pnl_pdf_endpoint(month: str, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    data = monthly_pnl(db, oid, month)
    me = month_end_summary(db, oid, month)
    name = get_settings_(db, oid)["outlet_name"]
    pdf = pnl_pdf(data, name, _label(month), me["summary"])
    fname = f"PnL-{name.replace(' ', '')}-{month}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/dashboard")
def dashboard(month: str, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    p = monthly_pnl(db, oid, month)
    lines = {ln["key"]: ln for ln in p["lines"]}
    _, end = month_bounds(month)
    today = min(date.today(), end)

    latest = db.scalars(
        select(Audit).where(Audit.outlet_id == oid, Audit.kind != "opening").order_by(Audit.date.desc(), Audit.id.desc())
    ).first()
    audit_block = None
    if latest:
        res = compute_audit_chain(db, oid, latest.id)[latest.id]
        flagged = sorted(
            (r for r in res["rows"] if r["flagged"]), key=lambda r: -abs(r["variance_value"] or 0)
        )[:8]
        audit_block = {
            "id": latest.id,
            "date": latest.date.isoformat(),
            "kind": latest.kind,
            "status": latest.status,
            "summary": res["summary"],
            "top_flagged": flagged,
        }

    levels = stock_levels(db, oid, today)
    items = list(db.scalars(select(Item).where(Item.outlet_id == oid, Item.active.is_(True))))
    book = PriceBook(db, oid, today, items)
    unpriced = [i.name for i in items if book.purchase_price(i.id, today) == 0]
    credit = outstanding_by_vendor(db, oid)
    return {
        "month": month,
        "kpis": {
            "net_sales": lines["net_sales"]["value"],
            "consumption": lines["consumption"]["value"],
            "food_cost_pct": p["ratios"]["food_cost_pct"],
            "gross_cost_pct": p["ratios"]["gross_cost_pct"],
            "ebitda": lines["ebitda"]["value"],
            "ebitda_pct": lines["ebitda"]["pct"],
            "wastage": lines["wastage"]["value"],
            "wage_cost_entered": p["wage_cost_entered"],
        },
        "series": daily_series(db, oid, month),
        "stations": p["stations"],
        "audit": audit_block,
        "stock": {
            "order_now": sum(1 for l in levels if l["status"] == "order_now"),
            "order": sum(1 for l in levels if l["status"] == "order"),
            "urgent": [l for l in levels if l["status"] == "order_now"][:8],
        },
        "reviews": review_counts(db, oid),
        "credit_outstanding": round(sum(c["outstanding"] for c in credit), 2),
        "pending": pending_rows(db, oid, date.today())[:10],
        "pending_count": len(pending_rows(db, oid, date.today())),
        "unpriced_items": unpriced,
    }
