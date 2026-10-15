"""Stock movements, audits and min/par levels (see PLAN.md for the rules)."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Audit, AuditCount, Issue, Item, PurchaseBill, PurchaseLine, Setting
from .pricing import PriceBook, month_bounds

FAR_PAST = date(1900, 1, 1)


def get_setting(db: Session, outlet_id: int, key: str, default: str) -> str:
    row = db.get(Setting, (outlet_id, key))
    return row.value if row else default


def variance_threshold(db: Session, outlet_id: int) -> float:
    return float(get_setting(db, outlet_id, "variance_threshold_pct", "2"))


def movements(db: Session, outlet_id: int, after: date, upto: date) -> dict[int, dict[str, float]]:
    """Per item, in consumption units, for dates in (after, upto]."""
    out: dict[int, dict[str, float]] = defaultdict(lambda: {"purchased": 0.0, "issued": 0.0})
    q = (
        select(PurchaseLine.item_id, func.sum(PurchaseLine.qty * func.coalesce(func.nullif(Item.conversion_ratio, 0), 1)))
        .join(PurchaseBill, PurchaseBill.id == PurchaseLine.bill_id)
        .join(Item, Item.id == PurchaseLine.item_id)
        .where(PurchaseBill.outlet_id == outlet_id, PurchaseBill.date > after, PurchaseBill.date <= upto)
        .group_by(PurchaseLine.item_id)
    )
    for item_id, qty in db.execute(q):
        out[item_id]["purchased"] = float(qty or 0)
    q = (
        select(Issue.item_id, func.sum(Issue.qty))
        .where(Issue.outlet_id == outlet_id, Issue.date > after, Issue.date <= upto)
        .group_by(Issue.item_id)
    )
    for item_id, qty in db.execute(q):
        out[item_id]["issued"] = float(qty or 0)
    return out


def ordered_audits(db: Session, outlet_id: int) -> list[Audit]:
    return list(db.scalars(select(Audit).where(Audit.outlet_id == outlet_id).order_by(Audit.date, Audit.id)))


def _counts(db: Session, audit_id: int) -> dict[int, float]:
    return {
        r.item_id: float(r.counted_qty)
        for r in db.scalars(select(AuditCount).where(AuditCount.audit_id == audit_id))
    }


def compute_segment(
    items: list[Item],
    opening: dict[int, float],
    moves: dict[int, dict[str, float]],
    counts: dict[int, float],
    book: PriceBook,
    on: date,
    threshold: float,
) -> tuple[list[dict], dict[int, float]]:
    """Rows for one audit and the closing stock map (counted if counted, else ideal)."""
    rows, closing = [], {}
    for it in items:
        op = opening.get(it.id, 0.0)
        mv = moves.get(it.id, {"purchased": 0.0, "issued": 0.0})
        available = op + mv["purchased"]
        ideal = available - mv["issued"]
        counted = counts.get(it.id)
        closing[it.id] = counted if counted is not None else ideal
        unit_cost = book.consumption_price(it.id, on)
        variance = None if counted is None else ideal - counted
        # variance % is measured against expected stock (opening + purchases - consumed)
        if variance is None:
            pct = None
        elif abs(ideal) > 1e-9:
            pct = variance / abs(ideal) * 100
        else:
            pct = 0.0 if abs(variance) < 1e-9 else (100.0 if variance > 0 else -100.0)
        if counted is None and abs(op) < 1e-9 and all(abs(v) < 1e-9 for v in mv.values()):
            continue  # nothing happened and nothing counted: keep the sheet short
        rows.append(
            {
                "item_id": it.id,
                "name": it.name,
                "category": it.category,
                "unit": it.consumption_unit,
                "opening": round(op, 3),
                "purchased": round(mv["purchased"], 3),
                "total_available": round(available, 3),
                "issued": round(mv["issued"], 3),
                "ideal": round(ideal, 3),
                "counted": counted,
                "variance": None if variance is None else round(variance, 3),
                "variance_pct": None if pct is None else round(pct, 2),
                "flagged": pct is not None and abs(pct) > threshold,
                "unit_cost": round(unit_cost, 2),
                "variance_value": None if variance is None else round(variance * unit_cost, 2),
                "closing_value": round(closing[it.id] * unit_cost, 2),
            }
        )
    return rows, closing


def _summary(rows: list[dict]) -> dict:
    counted = [r for r in rows if r["variance_value"] is not None]
    return {
        "items_counted": sum(1 for r in rows if r["counted"] is not None),
        "items_flagged": sum(1 for r in rows if r["flagged"]),
        "shortage_value": round(sum(r["variance_value"] for r in counted if r["variance_value"] > 0), 2),
        "excess_value": round(-sum(r["variance_value"] for r in counted if r["variance_value"] < 0), 2),
        "net_variance_value": round(sum(r["variance_value"] for r in counted), 2),
        "closing_stock_value": round(sum(r["closing_value"] for r in rows), 2),
    }


def compute_audit_chain(db: Session, outlet_id: int, upto_audit_id: int | None = None) -> dict[int, dict]:
    """Walk audits in date order from the most recent opening count; returns per-audit results.

    Each audit's opening is the previous audit's closing. Walking is cheap for one outlet
    (a few dozen audits a year) and always reflects edits to past purchases or issues.
    """
    audits = ordered_audits(db, outlet_id)
    if upto_audit_id is not None:
        idx = next(i for i, a in enumerate(audits) if a.id == upto_audit_id)
        audits = audits[: idx + 1]
    start = 0
    for i in range(len(audits) - 1, -1, -1):
        if audits[i].kind == "opening":
            start = i
            break
    audits = audits[start:]
    if not audits:
        return {}
    items = list(db.scalars(select(Item).where(Item.outlet_id == outlet_id).order_by(Item.category, Item.name)))
    book = PriceBook(db, outlet_id, audits[-1].date, items)
    threshold = variance_threshold(db, outlet_id)
    results, opening, prev_date = {}, {}, FAR_PAST
    for a in audits:
        counts = _counts(db, a.id)
        if a.kind == "opening":
            opening, prev_date = {}, FAR_PAST
            moves: dict = {}
        else:
            moves = movements(db, outlet_id, prev_date, a.date)
        rows, closing = compute_segment(items, opening, moves, counts, book, a.date, threshold)
        if a.kind == "opening":
            for r in rows:  # an opening count has no history: it simply sets stock
                r.update(variance=None, variance_pct=None, flagged=False, variance_value=None)
                r["ideal"] = r["counted"] if r["counted"] is not None else r["ideal"]
        results[a.id] = {
            "rows": rows,
            "closing": closing,
            "previous_date": None if prev_date == FAR_PAST else prev_date.isoformat(),
            "summary": _summary(rows),
        }
        opening, prev_date = closing, a.date
    return results


def month_end_summary(db: Session, outlet_id: int, month: str) -> dict:
    """The old MonthlyAuditSheet: opening at month start, whole-month movements, month-end count."""
    start, end = month_bounds(month)
    audits = ordered_audits(db, outlet_id)
    me = next((a for a in audits if a.kind == "month_end" and start <= a.date <= end), None)
    if me is None:
        return {"month": month, "month_end_audit": None, "rows": [], "summary": None}
    before = [a for a in audits if a.date < start]
    chain = compute_audit_chain(db, outlet_id, before[-1].id) if before else {}
    opening = chain[before[-1].id]["closing"] if before else {}
    opening_date = before[-1].date if before else FAR_PAST
    # an opening count inside the month resets the baseline
    inside_opening = [a for a in audits if a.kind == "opening" and start <= a.date <= me.date]
    if inside_opening:
        oa = inside_opening[-1]
        opening, opening_date = _counts(db, oa.id), oa.date
    items = list(db.scalars(select(Item).where(Item.outlet_id == outlet_id).order_by(Item.category, Item.name)))
    book = PriceBook(db, outlet_id, me.date, items)
    rows, _ = compute_segment(
        items,
        opening,
        movements(db, outlet_id, opening_date, me.date),
        _counts(db, me.id),
        book,
        me.date,
        variance_threshold(db, outlet_id),
    )
    return {
        "month": month,
        "month_end_audit": {"id": me.id, "date": me.date.isoformat(), "status": me.status},
        "opening_from": None if opening_date == FAR_PAST else opening_date.isoformat(),
        "rows": rows,
        "summary": _summary(rows),
    }


def _base_stock(db: Session, outlet_id: int, upto: date) -> tuple[dict[int, float], date]:
    audits = [a for a in ordered_audits(db, outlet_id) if a.date <= upto]
    if not audits:
        return {}, FAR_PAST
    chain = compute_audit_chain(db, outlet_id, audits[-1].id)
    return chain[audits[-1].id]["closing"], audits[-1].date


def estimated_stock(db: Session, outlet_id: int, upto: date) -> dict[int, float]:
    """Store stock per item at the end of `upto`: last audit's closing + purchases - issues since."""
    base, base_date = _base_stock(db, outlet_id, upto)
    out = dict(base)
    if base_date < upto:
        for iid, mv in movements(db, outlet_id, base_date, upto).items():
            out[iid] = out.get(iid, 0.0) + mv["purchased"] - mv["issued"]
    return out


def stock_levels(db: Session, outlet_id: int, today: date) -> list[dict]:
    """Current estimated stock vs min/par (the old MinimumStockSheet)."""
    items = list(
        db.scalars(
            select(Item).where(Item.outlet_id == outlet_id, Item.active.is_(True)).order_by(Item.category, Item.name)
        )
    )
    base, base_date = _base_stock(db, outlet_id, today)
    since = movements(db, outlet_id, base_date, today)
    # last full calendar month's issues
    first_this = today.replace(day=1)
    last_month_end = first_this - timedelta(days=1)
    lm_start = last_month_end.replace(day=1)
    usage = {
        item_id: float(q or 0)
        for item_id, q in db.execute(
            select(Issue.item_id, func.sum(Issue.qty))
            .where(Issue.outlet_id == outlet_id, Issue.date >= lm_start, Issue.date <= last_month_end)
            .group_by(Issue.item_id)
        )
    }
    out = []
    for it in items:
        mv = since.get(it.id, {"purchased": 0.0, "issued": 0.0})
        est = base.get(it.id, 0.0) + mv["purchased"] - mv["issued"]
        m = usage.get(it.id, 0.0)
        min_stock = math.floor((m / 4 * 1.25) * 100) / 100
        par = math.floor(m / 4 * 1.5)
        if m <= 0:
            status, suggest = "no_usage", 0.0
        elif est <= min_stock:
            status, suggest = "order_now", max(par - est, 0)
        elif est <= par:
            status, suggest = "order", max(par - est, 0)
        else:
            status, suggest = "ok", 0.0
        ratio = it.conversion_ratio if it.conversion_ratio and it.conversion_ratio > 0 else 1
        out.append(
            {
                "item_id": it.id,
                "name": it.name,
                "category": it.category,
                "unit": it.consumption_unit,
                "purchase_unit": it.purchase_unit,
                "estimated_stock": round(est, 3),
                "last_audit_date": None if base_date == FAR_PAST else base_date.isoformat(),
                "last_month_usage": round(m, 3),
                "min_stock": min_stock,
                "par_stock": par,
                "status": status,
                "suggested_qty": round(suggest, 3),
                "suggested_purchase_qty": math.ceil(suggest / ratio) if suggest > 0 else 0,
            }
        )
    return out
