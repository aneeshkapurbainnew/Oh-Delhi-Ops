from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import outlet_id
from ..db import get_db
from ..models import Issue, Item, Station, StationItem, Wastage
from ..services.pnl import wastage_rows
from ..services.pricing import PriceBook, days_in, month_bounds

router = APIRouter(tags=["issues"])


def _station(db: Session, station_id: int, oid: int) -> Station:
    s = db.get(Station, station_id)
    if s is None or s.outlet_id != oid:
        raise HTTPException(404, f"Station {station_id} not found.")
    return s


def _station_items(db: Session, station_id: int) -> list[Item]:
    return list(
        db.scalars(
            select(Item)
            .join(StationItem, StationItem.item_id == Item.id)
            .where(StationItem.station_id == station_id, Item.active.is_(True))
            .order_by(StationItem.sort, Item.name)
        )
    )


class IssueLine(BaseModel):
    item_id: int
    qty: float | None = Field(default=None, ge=0)


class IssueDayIn(BaseModel):
    date: date
    station_id: int
    lines: list[IssueLine]


@router.get("/issues/day")
def issue_day(on: date, station_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    _station(db, station_id, oid)
    items = _station_items(db, station_id)
    existing = {
        i.item_id: float(i.qty)
        for i in db.scalars(select(Issue).where(Issue.date == on, Issue.station_id == station_id))
    }
    # items issued that day but no longer on the station list still show up
    extra_ids = set(existing) - {i.id for i in items}
    if extra_ids:
        items += list(db.scalars(select(Item).where(Item.id.in_(extra_ids))))
    book = PriceBook(db, oid, on, items)
    rows = []
    for it in items:
        price = book.consumption_price(it.id, on)
        qty = existing.get(it.id)
        rows.append(
            {
                "item_id": it.id,
                "name": it.name,
                "category": it.category,
                "unit": it.consumption_unit,
                "unit_cost": round(price, 2),
                "qty": qty,
                "cost": round((qty or 0) * price, 2),
            }
        )
    return {"date": on.isoformat(), "station_id": station_id, "rows": rows, "total_cost": round(sum(r["cost"] for r in rows), 2)}


@router.put("/issues/day")
def save_issue_day(body: IssueDayIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    _station(db, body.station_id, oid)
    for line in body.lines:
        db.execute(
            delete(Issue).where(
                Issue.date == body.date, Issue.station_id == body.station_id, Issue.item_id == line.item_id
            )
        )
        if line.qty:
            db.add(Issue(outlet_id=oid, date=body.date, station_id=body.station_id, item_id=line.item_id, qty=line.qty))
    db.commit()
    return issue_day(body.date, body.station_id, db, oid)


@router.get("/issues/month")
def issue_month(month: str, station_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    """The month grid, like the old station sheets: items x days, plus a daily cost row."""
    _station(db, station_id, oid)
    start, end = month_bounds(month)
    days = days_in(month)
    grid: dict[int, dict[str, float]] = defaultdict(dict)
    for i in db.scalars(
        select(Issue).where(Issue.station_id == station_id, Issue.date >= start, Issue.date <= end)
    ):
        grid[i.item_id][i.date.isoformat()] = float(i.qty)
    items = _station_items(db, station_id)
    extra = set(grid) - {i.id for i in items}
    if extra:
        items += list(db.scalars(select(Item).where(Item.id.in_(extra))))
    book = PriceBook(db, oid, end, items)
    day_cost = {d.isoformat(): 0.0 for d in days}
    rows = []
    for it in items:
        qtys = grid.get(it.id, {})
        cost = 0.0
        for d in days:
            q = qtys.get(d.isoformat())
            if q:
                c = q * book.consumption_price(it.id, d)
                day_cost[d.isoformat()] += c
                cost += c
        rows.append(
            {
                "item_id": it.id,
                "name": it.name,
                "unit": it.consumption_unit,
                "qty": qtys,
                "total_qty": round(sum(qtys.values()), 3),
                "total_cost": round(cost, 2),
            }
        )
    return {
        "month": month,
        "days": [d.isoformat() for d in days],
        "rows": rows,
        "day_cost": {k: round(v, 2) for k, v in day_cost.items()},
        "total_cost": round(sum(day_cost.values()), 2),
    }


# ---------- wastage ----------------------------------------------------------------------------
class WastageIn(BaseModel):
    date: date
    dish: str = Field(min_length=1, max_length=160)
    station_id: int | None = None
    qty: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=30)
    value: float = Field(gt=0)  # rupees
    reason: str = Field(min_length=1, max_length=80)
    notes: str | None = None


WASTAGE_REASONS = [
    "Over-prepared / leftover",
    "Returned by customer",
    "Wrong order / remake",
    "Burnt / cooking error",
    "Spoiled before service",
    "Dropped / spilled",
    "Other",
]


@router.get("/wastage/reasons")
def wastage_reasons():
    return WASTAGE_REASONS


@router.get("/wastage")
def list_wastage(month: str, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    rows = wastage_rows(db, oid, month)
    by_station: dict[str, float] = defaultdict(float)
    for r in rows:
        by_station[r["station"] or "No station"] += r["value"]
    return {
        "rows": rows,
        "total": round(sum(r["value"] for r in rows), 2),
        "by_station": [{"name": k, "value": round(v, 2)} for k, v in sorted(by_station.items(), key=lambda x: -x[1])],
    }


@router.post("/wastage", status_code=201)
def add_wastage(body: WastageIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    if body.station_id is not None:
        _station(db, body.station_id, oid)
    w = Wastage(outlet_id=oid, **body.model_dump())
    db.add(w)
    db.commit()
    return {"id": w.id}


@router.delete("/wastage/{wastage_id}", status_code=204)
def delete_wastage(wastage_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    w = db.get(Wastage, wastage_id)
    if w is None or w.outlet_id != oid:
        raise HTTPException(404, "Wastage entry not found.")
    db.delete(w)
    db.commit()
