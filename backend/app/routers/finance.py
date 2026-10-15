from collections import defaultdict
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import outlet_id
from ..db import get_db
from ..models import Channel, ChannelCost, DailySales, Expense, ExpenseCategory, MonthlyInput
from ..services.pricing import days_in, month_bounds

router = APIRouter(tags=["finance"])

MONTH = Field(pattern=r"^\d{4}-\d{2}$")


# ---------- sales ---------------------------------------------------------------------------
class SalesRow(BaseModel):
    date: date
    gross_sale: float = Field(default=0, ge=0)
    complimentary: float = Field(default=0, ge=0)
    net_sales: float = Field(default=0, ge=0)


class SalesIn(BaseModel):
    rows: list[SalesRow]


@router.get("/sales")
def get_sales(month: str, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    start, end = month_bounds(month)
    have = {
        s.date: s
        for s in db.scalars(
            select(DailySales).where(DailySales.outlet_id == oid, DailySales.date >= start, DailySales.date <= end)
        )
    }
    rows = []
    for d in days_in(month):
        s = have.get(d)
        rows.append(
            {
                "date": d.isoformat(),
                "gross_sale": s.gross_sale if s else None,
                "complimentary": s.complimentary if s else None,
                "net_sales": s.net_sales if s else None,
            }
        )
    tot = lambda k: round(sum(r[k] or 0 for r in rows), 2)  # noqa: E731
    return {
        "rows": rows,
        "totals": {"gross_sale": tot("gross_sale"), "complimentary": tot("complimentary"), "net_sales": tot("net_sales")},
    }


@router.put("/sales")
def put_sales(body: SalesIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    for r in body.rows:
        db.execute(delete(DailySales).where(DailySales.outlet_id == oid, DailySales.date == r.date))
        if r.gross_sale or r.complimentary or r.net_sales:
            db.add(DailySales(outlet_id=oid, **r.model_dump()))
    db.commit()
    if not body.rows:
        return {"ok": True}
    return get_sales(body.rows[0].date.strftime("%Y-%m"), db, oid)


# ---------- channel costs (discount / delivery / ads) -----------------------------------
Kind = Literal["discount", "delivery", "ads"]


class CellIn(BaseModel):
    date: date
    row_id: int
    amount: float | None = Field(default=None, ge=0)


class GridIn(BaseModel):
    cells: list[CellIn]


def _grid(month: str, rows: list[dict], values: dict[tuple[int, str], float]) -> dict:
    days = [d.isoformat() for d in days_in(month)]
    day_tot = defaultdict(float)
    out = []
    for r in rows:
        vals = {d: values[(r["id"], d)] for d in days if (r["id"], d) in values}
        for d, v in vals.items():
            day_tot[d] += v
        out.append(r | {"values": vals, "total": round(sum(vals.values()), 2)})
    return {
        "days": days,
        "rows": out,
        "day_totals": {d: round(day_tot.get(d, 0), 2) for d in days},
        "total": round(sum(day_tot.values()), 2),
    }


@router.get("/channel-costs")
def get_channel_costs(month: str, kind: Kind, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    start, end = month_bounds(month)
    channels = [
        c
        for c in db.scalars(select(Channel).where(Channel.outlet_id == oid).order_by(Channel.sort, Channel.id))
        if kind in c.kinds.split(",")
    ]
    values = {
        (c.channel_id, c.date.isoformat()): float(c.amount)
        for c in db.scalars(
            select(ChannelCost).where(
                ChannelCost.outlet_id == oid, ChannelCost.kind == kind, ChannelCost.date >= start, ChannelCost.date <= end
            )
        )
    }
    # inactive channels stay visible only if they have values this month
    used = {cid for cid, _ in values}
    rows = [
        {"id": c.id, "label": c.brand, "group": c.platform, "active": c.active}
        for c in channels
        if c.active or c.id in used
    ]
    return _grid(month, rows, values)


@router.put("/channel-costs")
def put_channel_costs(kind: Kind, body: GridIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    for c in body.cells:
        ch = db.get(Channel, c.row_id)
        if ch is None or ch.outlet_id != oid:
            raise HTTPException(400, f"Unknown channel {c.row_id}.")
        db.execute(
            delete(ChannelCost).where(
                ChannelCost.date == c.date, ChannelCost.channel_id == c.row_id, ChannelCost.kind == kind
            )
        )
        if c.amount:
            db.add(ChannelCost(outlet_id=oid, date=c.date, channel_id=c.row_id, kind=kind, amount=c.amount))
    db.commit()
    return {"saved": len(body.cells)}


# ---------- expenses -----------------------------------------------------------------------
@router.get("/expenses")
def get_expenses(month: str, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    start, end = month_bounds(month)
    values = {
        (e.category_id, e.date.isoformat()): float(e.amount)
        for e in db.scalars(
            select(Expense).where(Expense.outlet_id == oid, Expense.date >= start, Expense.date <= end)
        )
    }
    used = {cid for cid, _ in values}
    cats = db.scalars(
        select(ExpenseCategory).where(ExpenseCategory.outlet_id == oid).order_by(ExpenseCategory.sort)
    )
    rows = [{"id": c.id, "label": c.name, "group": None, "active": c.active} for c in cats if c.active or c.id in used]
    return _grid(month, rows, values)


@router.put("/expenses")
def put_expenses(body: GridIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    for c in body.cells:
        cat = db.get(ExpenseCategory, c.row_id)
        if cat is None or cat.outlet_id != oid:
            raise HTTPException(400, f"Unknown expense category {c.row_id}.")
        db.execute(delete(Expense).where(Expense.date == c.date, Expense.category_id == c.row_id))
        if c.amount:
            db.add(Expense(outlet_id=oid, date=c.date, category_id=c.row_id, amount=c.amount))
    db.commit()
    return {"saved": len(body.cells)}


# ---------- monthly inputs (wage cost from Attendio) ------------------------------------
class MonthlyIn(BaseModel):
    wage_cost: float = Field(ge=0)
    days_of_operation: int | None = Field(default=None, ge=0, le=31)


@router.get("/monthly-inputs/{month}")
def get_monthly(month: str, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    mi = db.get(MonthlyInput, (oid, month))
    return {"month": month, "wage_cost": mi.wage_cost if mi else 0, "days_of_operation": mi.days_of_operation if mi else None}


@router.put("/monthly-inputs/{month}")
def put_monthly(month: str, body: MonthlyIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    month_bounds(month)  # validates
    mi = db.get(MonthlyInput, (oid, month))
    if mi is None:
        mi = MonthlyInput(outlet_id=oid, month=month)
        db.add(mi)
    mi.wage_cost, mi.days_of_operation = body.wage_cost, body.days_of_operation
    db.commit()
    return get_monthly(month, db, oid)
