from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import outlet_id
from ..db import get_db
from ..models import Item, PriceEntry
from ..services.pricing import PriceBook, month_bounds, period_range

router = APIRouter(prefix="/prices", tags=["prices"])


class PriceLine(BaseModel):
    item_id: int
    price: float | None = Field(default=None, ge=0)  # None clears the manual price


class DailyPricesIn(BaseModel):
    date: date
    prices: list[PriceLine]


class WeeklyPricesIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    period: int = Field(ge=1, le=3)
    prices: list[PriceLine]


def _items(db: Session, oid: int, mode: str) -> list[Item]:
    q = select(Item).where(Item.outlet_id == oid, Item.pricing_mode == mode, Item.active.is_(True))
    return list(db.scalars(q.order_by(Item.category, Item.name)))


@router.get("/daily")
def daily_prices(on: date, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    items = _items(db, oid, "daily")
    book = PriceBook(db, oid, on, items)
    today_entries = {
        (e.item_id, e.source): e.price
        for e in db.scalars(select(PriceEntry).where(PriceEntry.outlet_id == oid, PriceEntry.date == on))
    }
    out = []
    for it in items:
        price, from_date = book.daily_price(it.id, on)
        ratio = it.conversion_ratio or 1
        out.append(
            {
                "item_id": it.id,
                "name": it.name,
                "category": it.category,
                "purchase_unit": it.purchase_unit,
                "consumption_unit": it.consumption_unit,
                "conversion_ratio": ratio,
                "price": round(price, 2),
                "consumption_price": round(price / ratio, 2),
                "manual_price": today_entries.get((it.id, "manual")),
                "purchase_price": today_entries.get((it.id, "purchase")),
                "price_from": from_date.isoformat() if from_date else None,
                "carried_forward": from_date is not None and from_date < on,
                "never_priced": from_date is None or price == 0,
            }
        )
    return out


@router.put("/daily")
def set_daily_prices(body: DailyPricesIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    for line in body.prices:
        db.execute(
            delete(PriceEntry).where(
                PriceEntry.outlet_id == oid,
                PriceEntry.item_id == line.item_id,
                PriceEntry.date == body.date,
                PriceEntry.source == "manual",
            )
        )
        if line.price is not None:
            db.add(PriceEntry(outlet_id=oid, item_id=line.item_id, date=body.date, price=line.price, source="manual"))
    db.commit()
    return daily_prices(body.date, db, oid)


@router.get("/weekly")
def weekly_prices(month: str, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    start, end = month_bounds(month)
    items = _items(db, oid, "weekly_avg")
    book = PriceBook(db, oid, end, items)
    manual = {}
    for e in db.scalars(
        select(PriceEntry).where(
            PriceEntry.outlet_id == oid,
            PriceEntry.source == "manual",
            PriceEntry.date >= start,
            PriceEntry.date <= end,
        )
    ):
        p = 1 if e.date.day <= 10 else 2 if e.date.day <= 20 else 3
        manual[(e.item_id, p)] = e.price
    out = []
    for it in items:
        pp = book.period_prices(it.id, start.year, start.month)
        ratio = it.conversion_ratio or 1
        out.append(
            {
                "item_id": it.id,
                "name": it.name,
                "category": it.category,
                "purchase_unit": it.purchase_unit,
                "consumption_unit": it.consumption_unit,
                "conversion_ratio": ratio,
                "periods": [
                    {
                        "price": round(x["price"], 2),
                        "carried": x["carried"],
                        "manual": manual.get((it.id, n + 1)),
                    }
                    for n, x in enumerate(pp["periods"])
                ],
                "average": round(pp["average"], 2),
                "consumption_price": round(pp["average"] / ratio, 2),
                "never_priced": pp["average"] == 0,
            }
        )
    return out


@router.put("/weekly")
def set_weekly_prices(body: WeeklyPricesIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    y, m = (int(x) for x in body.month.split("-"))
    p_start, p_end = period_range(y, m, body.period)
    for line in body.prices:
        db.execute(
            delete(PriceEntry).where(
                PriceEntry.outlet_id == oid,
                PriceEntry.item_id == line.item_id,
                PriceEntry.source == "manual",
                PriceEntry.date >= p_start,
                PriceEntry.date <= p_end,
            )
        )
        if line.price is not None:
            db.add(PriceEntry(outlet_id=oid, item_id=line.item_id, date=p_start, price=line.price, source="manual"))
    db.commit()
    return weekly_prices(body.month, db, oid)


@router.get("/history/{item_id}")
def price_history(item_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    q = (
        select(PriceEntry)
        .where(PriceEntry.outlet_id == oid, PriceEntry.item_id == item_id)
        .order_by(PriceEntry.date.desc(), PriceEntry.id.desc())
        .limit(200)
    )
    return [{"date": e.date.isoformat(), "price": e.price, "source": e.source} for e in db.scalars(q)]
