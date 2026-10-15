from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import outlet_id
from ..db import get_db
from ..models import Audit, AuditCount, Item
from ..services.pricing import month_bounds
from ..services.stock import compute_audit_chain, month_end_summary, stock_levels, variance_threshold

router = APIRouter(tags=["audits"])

KIND_LABEL = {"opening": "Opening count", "spot": "Audit", "month_end": "Month-end audit"}


class AuditIn(BaseModel):
    date: date
    kind: Literal["opening", "spot", "month_end"] = "spot"
    notes: str | None = None


class CountLine(BaseModel):
    item_id: int
    counted_qty: float | None = Field(default=None, ge=0)  # None = not counted


class CountsIn(BaseModel):
    counts: list[CountLine]


def _audit(db: Session, audit_id: int, oid: int) -> Audit:
    a = db.get(Audit, audit_id)
    if a is None or a.outlet_id != oid:
        raise HTTPException(404, f"Audit {audit_id} not found.")
    return a


def audit_out(a: Audit, summary: dict | None = None) -> dict:
    return {
        "id": a.id,
        "date": a.date.isoformat(),
        "kind": a.kind,
        "kind_label": KIND_LABEL[a.kind],
        "status": a.status,
        "notes": a.notes,
        "closed_at": a.closed_at.isoformat() if a.closed_at else None,
        "summary": summary,
    }


@router.get("/audits")
def list_audits(db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    chain = compute_audit_chain(db, oid)
    audits = db.scalars(select(Audit).where(Audit.outlet_id == oid).order_by(Audit.date.desc(), Audit.id.desc()))
    return [audit_out(a, chain.get(a.id, {}).get("summary")) for a in audits]


@router.post("/audits", status_code=201)
def create_audit(body: AuditIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    if body.kind == "month_end":
        start, end = month_bounds(body.date.strftime("%Y-%m"))
        exists = db.scalar(
            select(Audit.id).where(
                Audit.outlet_id == oid, Audit.kind == "month_end", Audit.date >= start, Audit.date <= end
            )
        )
        if exists:
            raise HTTPException(409, "This month already has a month-end audit.")
    a = Audit(outlet_id=oid, **body.model_dump())
    db.add(a)
    db.commit()
    return audit_out(a)


@router.get("/audits/{audit_id}")
def get_audit(audit_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    a = _audit(db, audit_id, oid)
    chain = compute_audit_chain(db, oid, audit_id)
    res = chain.get(audit_id, {"rows": [], "summary": None, "previous_date": None})
    counted_ids = {r["item_id"] for r in res["rows"]}
    # the count sheet lists every active item, even ones with no movement yet
    items = db.scalars(
        select(Item).where(Item.outlet_id == oid, Item.active.is_(True)).order_by(Item.category, Item.name)
    )
    rows = list(res["rows"])
    for it in items:
        if it.id not in counted_ids:
            rows.append(
                {
                    "item_id": it.id, "name": it.name, "category": it.category, "unit": it.consumption_unit,
                    "opening": 0, "purchased": 0, "total_available": 0, "issued": 0,
                    "ideal": 0, "counted": None, "variance": None, "variance_pct": None, "flagged": False,
                    "unit_cost": None, "variance_value": None, "closing_value": 0,
                }
            )
    rows.sort(key=lambda r: (r["category"], r["name"]))
    return audit_out(a, res["summary"]) | {
        "previous_date": res["previous_date"],
        "threshold_pct": variance_threshold(db, oid),
        "rows": rows,
    }


@router.put("/audits/{audit_id}/counts")
def save_counts(audit_id: int, body: CountsIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    a = _audit(db, audit_id, oid)
    if a.status == "closed":
        raise HTTPException(400, "This audit is closed. Reopen it to change counts.")
    for c in body.counts:
        db.execute(delete(AuditCount).where(AuditCount.audit_id == a.id, AuditCount.item_id == c.item_id))
        if c.counted_qty is not None:
            db.add(AuditCount(audit_id=a.id, item_id=c.item_id, counted_qty=c.counted_qty))
    db.commit()
    return get_audit(audit_id, db, oid)


@router.post("/audits/{audit_id}/close")
def close_audit(audit_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    a = _audit(db, audit_id, oid)
    if a.kind == "month_end":
        start, _ = month_bounds(a.date.strftime("%Y-%m"))
        open_ones = list(
            db.scalars(
                select(Audit).where(
                    Audit.outlet_id == oid,
                    Audit.id != a.id,
                    Audit.status != "closed",
                    Audit.date >= start,
                    Audit.date <= a.date,
                )
            )
        )
        if open_ones:
            dates = ", ".join(x.date.strftime("%d %b") for x in open_ones)
            raise HTTPException(400, f"Close the other audits in this month first ({dates}).")
    a.status, a.closed_at = "closed", datetime.now(timezone.utc)
    db.commit()
    return audit_out(a)


@router.post("/audits/{audit_id}/reopen")
def reopen_audit(audit_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    a = _audit(db, audit_id, oid)
    a.status, a.closed_at = "draft", None
    db.commit()
    return audit_out(a)


@router.delete("/audits/{audit_id}", status_code=204)
def delete_audit(audit_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    a = _audit(db, audit_id, oid)
    db.delete(a)
    db.commit()


@router.get("/audits-monthly")
def monthly(month: str, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    return month_end_summary(db, oid, month)


@router.get("/stock/levels")
def levels(on: date | None = None, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    return stock_levels(db, oid, on or date.today())
