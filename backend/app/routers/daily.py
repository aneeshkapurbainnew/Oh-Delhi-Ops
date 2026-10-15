"""Daily ordering loop for perishables (vegetables, poultry, dairy, eggs, noodles, rumali).

1. Requisition: each station enters what it needs for a delivery date (evening before).
2. Plan: the manager reviews the totals, picks a vendor per item, and sends each vendor a WhatsApp order.
3. Receive: the store records what each vendor actually delivered (becomes a purchase bill).
4. Distribute: the store records what each station was given (becomes that station's issues).
5. Pending: anything a station asked for but didn't get is flagged until it's given or dismissed.

Requisitions and station quantities are in consumption units; vendor orders in purchase units.
"""
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from ..auth import outlet_id, require_user
from ..db import get_db
from ..models import DailyOrder, DailyOrderLine, Issue, Item, Requisition, Station, StationItem, User, Vendor
from ..services.stock import estimated_stock
from .purchases import BillIn, LineIn, create_bill, delete_bill, update_bill
from .setup import get_settings_

router = APIRouter(tags=["daily orders"])
EPS = 1e-9


def _ratio(it: Item) -> float:
    return it.conversion_ratio if it.conversion_ratio and it.conversion_ratio > 0 else 1.0


def _station(db: Session, station_id: int, oid: int) -> Station:
    s = db.get(Station, station_id)
    if s is None or s.outlet_id != oid:
        raise HTTPException(404, f"Station {station_id} not found.")
    return s


def _orders_for(db: Session, oid: int, on: date) -> list[DailyOrder]:
    return list(
        db.scalars(
            select(DailyOrder)
            .options(selectinload(DailyOrder.lines), selectinload(DailyOrder.vendor))
            .where(DailyOrder.outlet_id == oid, DailyOrder.date == on)
            .order_by(DailyOrder.id)
        )
    )


def _who(user: User | None) -> str:
    return user.name if user else "local dev"


# ---------------------------------------------------------------- 1. requisitions (chefs)
class ReqLine(BaseModel):
    item_id: int
    qty: float | None = Field(default=None, ge=0)


class ReqIn(BaseModel):
    date: date
    station_id: int
    lines: list[ReqLine]


@router.get("/requisitions")
def get_requisitions(on: date, station_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    _station(db, station_id, oid)
    have = {
        r.item_id: r
        for r in db.scalars(select(Requisition).where(Requisition.date == on, Requisition.station_id == station_id))
    }
    # every item on the station's list: daily-order items go to vendors tonight,
    # the rest (dry store) are handed over from store stock
    on_list = list(
        db.scalars(
            select(Item)
            .join(StationItem, StationItem.item_id == Item.id)
            .where(StationItem.station_id == station_id, Item.active.is_(True))
            .order_by(Item.daily_order.desc(), Item.category, Item.name)
        )
    )
    extra = set(have) - {i.id for i in on_list}
    items = on_list + (list(db.scalars(select(Item).where(Item.id.in_(extra)))) if extra else [])
    sent = any(o.status != "draft" for o in _orders_for(db, oid, on))
    return {
        "date": on.isoformat(),
        "station_id": station_id,
        "orders_sent": sent,
        "rows": [
            {
                "item_id": it.id,
                "name": it.name,
                "category": it.category,
                "unit": it.consumption_unit,
                "source": "vendor" if it.daily_order else "store",
                "qty": have[it.id].qty if it.id in have else None,
                "late": have[it.id].late if it.id in have else False,
                "updated_by": have[it.id].updated_by if it.id in have else None,
            }
            for it in items
        ],
    }


@router.put("/requisitions")
def save_requisitions(
    body: ReqIn,
    db: Session = Depends(get_db),
    oid: int = Depends(outlet_id),
    user: User | None = Depends(require_user),
):
    _station(db, body.station_id, oid)
    sent = any(o.status != "draft" for o in _orders_for(db, oid, body.date))
    daily_ids = set(
        db.scalars(select(Item.id).where(Item.id.in_([l.item_id for l in body.lines]), Item.daily_order.is_(True)))
    ) if body.lines else set()
    for line in body.lines:
        late_now = sent and line.item_id in daily_ids
        r = db.scalar(
            select(Requisition).where(
                Requisition.date == body.date, Requisition.station_id == body.station_id, Requisition.item_id == line.item_id
            )
        )
        if not line.qty:
            if r:
                db.delete(r)
            continue
        if r is None:
            r = Requisition(outlet_id=oid, date=body.date, station_id=body.station_id, item_id=line.item_id, qty=line.qty)
            db.add(r)
            r.late = late_now
        elif abs(r.qty - line.qty) > EPS:
            r.qty = line.qty
            r.late = r.late or late_now
        r.updated_by = _who(user)
    db.commit()
    return get_requisitions(body.date, body.station_id, db, oid)


# ---------------------------------------------------------------- 2. plan + send (manager)
class PlanLine(BaseModel):
    item_id: int
    vendor_id: int
    qty: float = Field(ge=0)  # purchase units


class PlanIn(BaseModel):
    date: date
    lines: list[PlanLine]


@router.get("/daily-orders/plan")
def get_plan(on: date, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    stations = {s.id: s.name for s in db.scalars(select(Station).where(Station.outlet_id == oid))}
    # only daily-order items are bought from vendors; dry store items are handed over from stock
    reqs = list(
        db.scalars(
            select(Requisition)
            .join(Item, Item.id == Requisition.item_id)
            .where(Requisition.outlet_id == oid, Requisition.date == on, Item.daily_order.is_(True))
        )
    )
    orders = _orders_for(db, oid, on)
    planned = defaultdict(list)
    for o in orders:
        for l in o.lines:
            planned[l.item_id].append({"vendor_id": o.vendor_id, "qty": l.qty_ordered, "order_id": o.id, "status": o.status})
    item_ids = {r.item_id for r in reqs} | set(planned)
    last_split = _last_splits(db, oid, on, item_ids)
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_(item_ids)))} if item_ids else {}
    # stock in the store at the end of the day before delivery
    on_hand = estimated_stock(db, oid, on - timedelta(days=1)) if items else {}
    by_item = defaultdict(list)
    for r in reqs:
        by_item[r.item_id].append(r)
    rows = []
    for iid, it in items.items():
        rs = by_item.get(iid, [])
        requested = sum(r.qty for r in rs)
        ratio = _ratio(it)
        suggested = requested / ratio
        suggested = math.ceil(suggested - 1e-9) if ratio > 1 else round(suggested, 3)
        p = planned.get(iid, [])
        split = last_split.get(iid)
        rows.append(
            {
                "item_id": iid,
                "name": it.name,
                "category": it.category,
                "consumption_unit": it.consumption_unit,
                "purchase_unit": it.purchase_unit,
                "conversion_ratio": ratio,
                "requested": round(requested, 3),
                "by_station": [
                    {"station": stations.get(r.station_id, "?"), "qty": r.qty, "late": r.late}
                    for r in sorted(rs, key=lambda r: stations.get(r.station_id, ""))
                ],
                "any_late": any(r.late for r in rs),
                "stock_on_hand": round(max(on_hand.get(iid, 0.0), 0.0), 3),
                "suggested_qty": suggested,
                "default_vendor_id": it.default_vendor_id,
                "planned": p,  # one entry per vendor this item is ordered from
                # last time this item was split across vendors: [{vendor_id, share}] (shares sum to 1)
                "last_split": split,
                # requested changed after the order went out
                "needs_resend": bool(any(x["status"] != "draft" for x in p) and any(r.late for r in rs)),
            }
        )
    rows.sort(key=lambda r: (r["category"], r["name"]))
    return {
        "date": on.isoformat(),
        "rows": rows,
        "orders": [{"id": o.id, "vendor_id": o.vendor_id, "status": o.status} for o in orders],
    }


@router.put("/daily-orders/plan")
def save_plan(body: PlanIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    orders = {o.vendor_id: o for o in _orders_for(db, oid, body.date)}
    received = {v for v, o in orders.items() if o.status == "received"}
    new = defaultdict(dict)
    for l in body.lines:
        if l.vendor_id in received:
            raise HTTPException(400, "That vendor's delivery is already received. Edit it on the Receive tab instead.")
        if l.qty > 0:
            new[l.vendor_id][l.item_id] = l.qty
    vendors = {v.id for v in db.scalars(select(Vendor).where(Vendor.id.in_(list(new))))} if new else set()
    if set(new) - vendors:
        raise HTTPException(400, "Choose a vendor for every item.")
    for vid in set(orders) | set(new):
        o = orders.get(vid)
        if o is not None and o.status == "received":
            continue
        if vid not in new:
            if o is not None:
                db.delete(o)
            continue
        if o is None:
            o = DailyOrder(outlet_id=oid, date=body.date, vendor_id=vid)
            db.add(o)
        old = {l.item_id: l.qty_ordered for l in o.lines}
        if o.status == "sent" and old != new[vid]:
            o.changed_after_send = True
        o.lines.clear()
        db.flush()
        for iid, q in new[vid].items():
            o.lines.append(DailyOrderLine(item_id=iid, qty_ordered=q))
    db.commit()
    return list_orders(body.date, db, oid)


def _last_splits(db: Session, oid: int, on: date, item_ids: set[int]) -> dict[int, list[dict]]:
    """For items ordered from 2+ vendors on their most recent earlier delivery date (last 30 days),
    the vendors and each one's share of that day's quantity."""
    if not item_ids:
        return {}
    rows = db.execute(
        select(DailyOrder.date, DailyOrder.vendor_id, DailyOrderLine.item_id, DailyOrderLine.qty_ordered)
        .join(DailyOrderLine, DailyOrderLine.order_id == DailyOrder.id)
        .where(
            DailyOrder.outlet_id == oid,
            DailyOrder.date < on,
            DailyOrder.date >= on - timedelta(days=30),
            DailyOrderLine.item_id.in_(item_ids),
            DailyOrderLine.qty_ordered > 0,
        )
    ).all()
    latest: dict[int, date] = {}
    for d, _, iid, _ in rows:
        latest[iid] = max(latest.get(iid, d), d)
    out = {}
    for iid, d in latest.items():
        parts = [(v, q) for dd, v, i, q in rows if i == iid and dd == d]
        total = sum(q for _, q in parts)
        if len(parts) > 1 and total > 0:
            out[iid] = [{"vendor_id": v, "share": round(q / total, 4)} for v, q in sorted(parts, key=lambda x: -x[1])]
    return out


def _phone(raw: str | None) -> str | None:
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) == 10:
        return "91" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "91" + digits[1:]
    return digits or None


def _fmt_qty(q: float) -> str:
    return str(int(q)) if abs(q - round(q)) < 1e-9 else f"{q:g}"


def order_message(outlet: str, on: date, lines: list[tuple[str, float, str]]) -> str:
    head = f"*{outlet}* - order for {on.strftime('%a %d %b')}"
    body = "\n".join(f"{n}. {name} - {_fmt_qty(q)} {unit}" for n, (name, q, unit) in enumerate(lines, start=1))
    return f"{head}\n\n{body}\n\nPlease confirm. Thank you!"


def order_out(o: DailyOrder, items: dict[int, Item], outlet: str) -> dict:
    lines = [
        {
            "item_id": l.item_id,
            "name": items[l.item_id].name,
            "purchase_unit": items[l.item_id].purchase_unit,
            "qty_ordered": l.qty_ordered,
            "qty_received": l.qty_received,
            "rate": l.rate,
        }
        for l in o.lines
    ]
    lines.sort(key=lambda l: l["name"])
    msg = order_message(outlet, o.date, [(l["name"], l["qty_ordered"], l["purchase_unit"]) for l in lines if l["qty_ordered"] > 0])
    group = (o.vendor.whatsapp_group or "").strip() or None
    # groups can't be targeted by a link: open the share screen and let the user pick the group
    phone = None if group else _phone(o.vendor.phone)
    return {
        "id": o.id,
        "date": o.date.isoformat(),
        "vendor_id": o.vendor_id,
        "vendor": o.vendor.name,
        "vendor_phone": o.vendor.phone,
        "whatsapp_group": group,
        "status": o.status,
        "sent_at": o.sent_at.isoformat() if o.sent_at else None,
        "changed_after_send": o.changed_after_send,
        "purchase_bill_id": o.purchase_bill_id,
        "lines": lines,
        "message": msg,
        # wa.me opens WhatsApp with the text filled in; without a phone it lets you pick the chat
        "whatsapp_url": f"https://wa.me/{phone or ''}?text={quote(msg)}",
        "has_phone": phone is not None,
    }


@router.get("/daily-orders")
def list_orders(on: date, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    orders = _orders_for(db, oid, on)
    ids = {l.item_id for o in orders for l in o.lines}
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_(ids)))} if ids else {}
    outlet = get_settings_(db, oid)["outlet_name"]
    return [order_out(o, items, outlet) for o in sorted(orders, key=lambda o: o.vendor.name)]


def _order(db: Session, order_id: int, oid: int) -> DailyOrder:
    o = db.scalar(
        select(DailyOrder)
        .options(selectinload(DailyOrder.lines), selectinload(DailyOrder.vendor))
        .where(DailyOrder.id == order_id, DailyOrder.outlet_id == oid)
    )
    if o is None:
        raise HTTPException(404, "Order not found.")
    return o


@router.post("/daily-orders/{order_id}/sent")
def mark_sent(order_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    o = _order(db, order_id, oid)
    if o.status == "received":
        raise HTTPException(400, "This order is already received.")
    o.status, o.sent_at, o.changed_after_send = "sent", datetime.now(timezone.utc), False
    db.commit()
    return {"id": o.id, "status": o.status}


# ---------------------------------------------------------------- 3. receive from vendor (store)
class ReceiveLine(BaseModel):
    item_id: int
    qty_received: float = Field(ge=0)  # purchase units
    rate: float | None = Field(default=None, ge=0)


class ReceiveIn(BaseModel):
    bill_no: str | None = None
    payment_status: Literal["paid", "credit", "partial"] = "credit"
    amount_paid: float | None = Field(default=None, ge=0)
    notes: str | None = None
    lines: list[ReceiveLine]


@router.post("/daily-orders/{order_id}/receive")
def receive(order_id: int, body: ReceiveIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    o = _order(db, order_id, oid)
    got = [l for l in body.lines if l.qty_received > 0]
    if any(l.rate is None for l in got):
        raise HTTPException(400, "Enter a rate for every item that arrived.")
    by_item = {l.item_id: l for l in o.lines}
    for l in body.lines:
        line = by_item.get(l.item_id)
        if line is None:  # arrived without being ordered
            line = DailyOrderLine(item_id=l.item_id, qty_ordered=0)
            o.lines.append(line)
            by_item[l.item_id] = line
        line.qty_received, line.rate = l.qty_received, l.rate
    o.status = "received"
    db.flush()
    if got:
        bill = BillIn(
            vendor_id=o.vendor_id,
            date=o.date,
            bill_no=body.bill_no,
            payment_status=body.payment_status,
            amount_paid=body.amount_paid,
            notes=body.notes or "From daily order",
            lines=[LineIn(item_id=l.item_id, qty=l.qty_received, rate=l.rate) for l in got],
        )
        if o.purchase_bill_id:
            update_bill(o.purchase_bill_id, bill, db, oid)
        else:
            o.purchase_bill_id = create_bill(bill, db, oid)["id"]
    elif o.purchase_bill_id:
        bid, o.purchase_bill_id = o.purchase_bill_id, None
        db.flush()
        delete_bill(bid, db, oid)
    db.commit()
    return list_orders(o.date, db, oid)


@router.post("/daily-orders/{order_id}/reopen")
def reopen_receipt(order_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    """Back to 'sent' so the plan can change; the purchase bill stays until the next receipt."""
    o = _order(db, order_id, oid)
    if o.status == "received":
        o.status = "sent"
    db.commit()
    return {"id": o.id, "status": o.status}


# ---------------------------------------------------------------- 4. give to stations (store)
class GiveLine(BaseModel):
    item_id: int
    qty_given: float | None = Field(default=None, ge=0)  # consumption units


class GiveIn(BaseModel):
    date: date
    station_id: int
    lines: list[GiveLine]


def _given(db: Session, on: date, station_id: int | None = None) -> dict[tuple[int, int], float]:
    q = select(Issue.station_id, Issue.item_id, Issue.qty).where(Issue.date == on)
    if station_id:
        q = q.where(Issue.station_id == station_id)
    return {(s, i): float(qty) for s, i, qty in db.execute(q)}


def _vendor_status(db: Session, oid: int, on: date) -> dict[int, dict]:
    """Per item: what the vendor orders for that day say (ordered / received, in consumption units)."""
    out = {}
    orders = _orders_for(db, oid, on)
    ids = {l.item_id for o in orders for l in o.lines}
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_(ids)))} if ids else {}
    for o in orders:
        for l in o.lines:
            r = _ratio(items[l.item_id])
            d = out.setdefault(l.item_id, {"ordered": 0.0, "received": 0.0, "all_received": True, "vendors": [], "waiting": []})
            d["vendors"].append(o.vendor.name)
            if o.status != "received":
                d["waiting"].append(o.vendor.name)
            d["ordered"] += l.qty_ordered * r
            d["received"] += (l.qty_received or 0) * r
            d["all_received"] = d["all_received"] and o.status == "received"
    return out


def _reason(vs: dict | None, daily_order: bool = True, in_store: float | None = None, short: float = 0.0) -> str:
    if not daily_order:  # dry store item: comes from store stock, not a vendor
        if in_store is not None and in_store + EPS < short:
            return f"Only {_fmt_qty(round(max(in_store, 0), 3))} left in store"
        return "Not handed over yet"
    if vs is None:
        return "Not ordered from a vendor"
    if not vs["all_received"]:
        return f"Not received from {' and '.join(vs['waiting'])} yet"
    if vs["received"] + EPS < vs["ordered"]:
        who = " and ".join(vs["vendors"])
        return f"{who} short-supplied ({_fmt_qty(round(vs['received'], 3))} of {_fmt_qty(round(vs['ordered'], 3))})"
    return "Not handed over yet"


@router.get("/distribution")
def get_distribution(on: date, station_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    _station(db, station_id, oid)
    reqs = list(
        db.execute(
            select(Requisition, Item)
            .join(Item, Item.id == Requisition.item_id)
            .where(Requisition.date == on, Requisition.station_id == station_id)
            .order_by(Item.daily_order.desc(), Item.category, Item.name)
        )
    )
    given = _given(db, on, station_id)
    vs = _vendor_status(db, oid, on)
    in_store = estimated_stock(db, oid, on)
    rows = []
    for r, it in reqs:
        g = given.get((station_id, it.id))
        short = max(r.qty - (g or 0), 0)
        rows.append(
            {
                "requisition_id": r.id,
                "item_id": it.id,
                "name": it.name,
                "category": it.category,
                "unit": it.consumption_unit,
                "requested": r.qty,
                "given": g,
                "short": round(short, 3),
                "pending": short > EPS and r.dismissed_at is None,
                "dismissed": r.dismiss_reason if r.dismissed_at else None,
                "source": "vendor" if it.daily_order else "store",
                "reason": _reason(vs.get(it.id), it.daily_order, in_store.get(it.id, 0.0), short) if short > EPS else None,
                "in_store": round(in_store.get(it.id, 0.0), 3),
            }
        )
    return {"date": on.isoformat(), "station_id": station_id, "rows": rows}


@router.put("/distribution")
def save_distribution(body: GiveIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    _station(db, body.station_id, oid)
    for l in body.lines:
        db.execute(delete(Issue).where(Issue.date == body.date, Issue.station_id == body.station_id, Issue.item_id == l.item_id))
        if l.qty_given:
            db.add(Issue(outlet_id=oid, date=body.date, station_id=body.station_id, item_id=l.item_id, qty=l.qty_given))
    db.commit()
    return get_distribution(body.date, body.station_id, db, oid)


@router.get("/distribution/summary")
def distribution_summary(on: date, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    """Owner view: per station, what was asked for and what was given that day."""
    stations = list(db.scalars(select(Station).where(Station.outlet_id == oid, Station.active.is_(True)).order_by(Station.sort)))
    reqs = list(db.scalars(select(Requisition).where(Requisition.outlet_id == oid, Requisition.date == on)))
    given = _given(db, on)
    out = []
    for s in stations:
        rs = [r for r in reqs if r.station_id == s.id]
        full = sum(1 for r in rs if given.get((s.id, r.item_id), 0) + EPS >= r.qty)
        pend = sum(1 for r in rs if given.get((s.id, r.item_id), 0) + EPS < r.qty and r.dismissed_at is None)
        out.append({"station_id": s.id, "name": s.name, "requested_items": len(rs), "fully_given": full, "pending": pend})
    return out


# ---------------------------------------------------------------- 5. pending alerts
class DismissIn(BaseModel):
    requisition_ids: list[int]
    reason: str = Field(min_length=1, max_length=160)


def pending_rows(db: Session, oid: int, today: date, days: int = 7) -> list[dict]:
    start = today - timedelta(days=days)
    reqs = list(
        db.execute(
            select(Requisition, Item, Station)
            .join(Item, Item.id == Requisition.item_id)
            .join(Station, Station.id == Requisition.station_id)
            .where(
                Requisition.outlet_id == oid,
                Requisition.date >= start,
                Requisition.date <= today,
                Requisition.dismissed_at.is_(None),
            )
            .order_by(Requisition.date.desc(), Station.sort, Item.name)
        )
    )
    given_cache: dict[date, dict] = {}
    vs_cache: dict[date, dict] = {}
    stock_cache: dict[date, dict] = {}
    out = []
    for r, it, st in reqs:
        if r.date not in given_cache:
            given_cache[r.date] = _given(db, r.date)
            vs_cache[r.date] = _vendor_status(db, oid, r.date)
        g = given_cache[r.date].get((st.id, it.id), 0.0)
        if g + EPS >= r.qty:
            continue
        if not it.daily_order and r.date not in stock_cache:
            stock_cache[r.date] = estimated_stock(db, oid, r.date)
        in_store = stock_cache[r.date].get(it.id, 0.0) if not it.daily_order else None
        out.append(
            {
                "requisition_id": r.id,
                "date": r.date.isoformat(),
                "station_id": st.id,
                "station": st.name,
                "item_id": it.id,
                "item": it.name,
                "unit": it.consumption_unit,
                "requested": r.qty,
                "given": g,
                "short": round(r.qty - g, 3),
                "source": "vendor" if it.daily_order else "store",
                "reason": _reason(vs_cache[r.date].get(it.id), it.daily_order, in_store, r.qty - g),
            }
        )
    return out


@router.get("/pending")
def pending(days: int = 7, on: date | None = None, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    return pending_rows(db, oid, on or date.today(), days)


@router.get("/pending/count")
def pending_count(on: date | None = None, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    return {"count": len(pending_rows(db, oid, on or date.today()))}


@router.post("/pending/dismiss")
def dismiss(body: DismissIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id), user: User | None = Depends(require_user)):
    now = datetime.now(timezone.utc)
    for rid in body.requisition_ids:
        r = db.get(Requisition, rid)
        if r is None or r.outlet_id != oid:
            raise HTTPException(404, f"Request {rid} not found.")
        r.dismissed_at, r.dismiss_reason = now, f"{body.reason} ({_who(user)})"
    db.commit()
    return {"dismissed": len(body.requisition_ids)}
