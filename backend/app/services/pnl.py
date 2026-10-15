"""Consumption costing, the monthly P&L and the owner dashboard numbers."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    ChannelCost,
    DailySales,
    Expense,
    Issue,
    MonthlyInput,
    Review,
    Station,
    Wastage,
)
from .pricing import PriceBook, days_in, month_bounds


def _pct(part: float, whole: float) -> float | None:
    return round(part / whole * 100, 2) if whole else None


def station_costs(db: Session, outlet_id: int, month: str, book: PriceBook | None = None) -> dict:
    """Per station per day issue cost, at the price rules for each item."""
    start, end = month_bounds(month)
    book = book or PriceBook(db, outlet_id, end)
    per = defaultdict(lambda: defaultdict(float))
    for d, station_id, item_id, qty in db.execute(
        select(Issue.date, Issue.station_id, Issue.item_id, Issue.qty).where(
            Issue.outlet_id == outlet_id, Issue.date >= start, Issue.date <= end
        )
    ):
        per[station_id][d] += float(qty) * book.consumption_price(item_id, d)
    return per


def wastage_rows(db: Session, outlet_id: int, month: str) -> list[dict]:
    """Cooked-food wastage entered in rupees."""
    start, end = month_bounds(month)
    stations = {s.id: s.name for s in db.scalars(select(Station).where(Station.outlet_id == outlet_id))}
    q = (
        select(Wastage)
        .where(Wastage.outlet_id == outlet_id, Wastage.date >= start, Wastage.date <= end)
        .order_by(Wastage.date.desc(), Wastage.id.desc())
    )
    return [
        {
            "id": w.id,
            "date": w.date.isoformat(),
            "dish": w.dish,
            "qty": w.qty,
            "unit": w.unit,
            "station_id": w.station_id,
            "station": stations.get(w.station_id) if w.station_id else None,
            "reason": w.reason,
            "notes": w.notes,
            "value": round(float(w.value), 2),
        }
        for w in db.scalars(q)
    ]


def monthly_pnl(db: Session, outlet_id: int, month: str) -> dict:
    start, end = month_bounds(month)
    book = PriceBook(db, outlet_id, end)
    stations = list(db.scalars(select(Station).where(Station.outlet_id == outlet_id).order_by(Station.sort)))

    sales = list(
        db.scalars(
            select(DailySales).where(
                DailySales.outlet_id == outlet_id, DailySales.date >= start, DailySales.date <= end
            )
        )
    )
    gross = sum(s.gross_sale or 0 for s in sales)
    comp = sum(s.complimentary or 0 for s in sales)
    net = sum(s.net_sales or 0 for s in sales)
    total_gross = gross + comp

    def kind_total(kind: str) -> float:
        v = db.scalar(
            select(func.sum(ChannelCost.amount)).where(
                ChannelCost.outlet_id == outlet_id,
                ChannelCost.kind == kind,
                ChannelCost.date >= start,
                ChannelCost.date <= end,
            )
        )
        return float(v or 0)

    discount, delivery, ads = kind_total("discount"), kind_total("delivery"), kind_total("ads")
    expenses = float(
        db.scalar(
            select(func.sum(Expense.amount)).where(
                Expense.outlet_id == outlet_id, Expense.date >= start, Expense.date <= end
            )
        )
        or 0
    )

    per_station = station_costs(db, outlet_id, month, book)
    station_totals = [
        {"station_id": s.id, "name": s.name, "kind": s.kind, "cost": round(sum(per_station[s.id].values()), 2)}
        for s in stations
    ]
    consumption = sum(x["cost"] for x in station_totals)
    kitchen = sum(x["cost"] for x in station_totals if x["kind"] == "kitchen")
    packaging = sum(x["cost"] for x in station_totals if x["kind"] == "packaging")

    wastage = sum(w["value"] for w in wastage_rows(db, outlet_id, month))

    mi = db.get(MonthlyInput, (outlet_id, month))
    wage = float(mi.wage_cost) if mi else 0.0
    days_op = (mi.days_of_operation if mi and mi.days_of_operation else None) or sum(
        1 for s in sales if (s.gross_sale or 0) > 0
    )

    cogs = consumption + wastage
    gross_profit = net - cogs
    margin = gross_profit - wage
    ebitda = margin - expenses - ads - delivery

    def line(key, label, value, base=net):
        return {"key": key, "label": label, "value": round(value, 2), "pct": _pct(value, base)}

    return {
        "month": month,
        "days_of_operation": days_op,
        "wage_cost_entered": mi is not None and wage > 0,
        "lines": [
            line("gross_sale", "Gross sale", gross, gross),
            line("complimentary", "Complimentary food", comp, gross),
            line("discount", "Total discount", discount, gross),
            line("net_sales", "Net sales (with tax)", net),
            line("consumption", "Consumption cost", consumption),
            line("wastage", "Wastage (cooked food)", wastage),
            line("cogs", "Total COGS", cogs),
            line("gross_profit", "Gross profit", gross_profit),
            line("wage_cost", "Wage cost", wage),
            line("restaurant_margin", "Restaurant margin", margin),
            line("expenses", "Expenses", expenses),
            line("ads", "Ads cost", ads),
            line("delivery", "Delivery cost", delivery),
            line("ebitda", "Restaurant EBITDA", ebitda),
        ],
        "ratios": {
            "food_cost_pct": _pct(kitchen, net),
            "packaging_cost_pct": _pct(packaging, net),
            "gross_cost_pct": _pct(consumption, total_gross),
        },
        "stations": station_totals,
    }


def daily_series(db: Session, outlet_id: int, month: str) -> list[dict]:
    start, end = month_bounds(month)
    book = PriceBook(db, outlet_id, end)
    stations = {s.id: s for s in db.scalars(select(Station).where(Station.outlet_id == outlet_id))}
    per = station_costs(db, outlet_id, month, book)
    sales = {
        s.date: s
        for s in db.scalars(
            select(DailySales).where(
                DailySales.outlet_id == outlet_id, DailySales.date >= start, DailySales.date <= end
            )
        )
    }
    out = []
    for d in days_in(month):
        cost = sum(per[sid].get(d, 0) for sid in per)
        kitchen = sum(per[sid].get(d, 0) for sid in per if stations[sid].kind == "kitchen")
        s = sales.get(d)
        net = float(s.net_sales) if s else 0.0
        out.append(
            {
                "date": d.isoformat(),
                "net_sales": round(net, 2),
                "consumption_cost": round(cost, 2),
                "food_cost_pct": _pct(kitchen, net),
            }
        )
    return out


def review_counts(db: Session, outlet_id: int) -> dict:
    rows = db.execute(
        select(Review.status, func.count()).where(Review.outlet_id == outlet_id).group_by(Review.status)
    ).all()
    return {status: n for status, n in rows}


def today() -> date:
    return date.today()
