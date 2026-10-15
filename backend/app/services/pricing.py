"""Price rules (see PLAN.md).

weekly_avg items: month split into periods 1-10, 11-20, 21-end. A period's price is the average of
manual entries in it, else the average of purchase rates in it, else the previous period's price.
The month price is the average of the three period prices.

daily items: the price on a date is the manual entry that day, else the average purchase rate that
day, else the most recent earlier price.

All prices are per purchase unit; consumption price = purchase price / conversion ratio.
"""
from __future__ import annotations

import bisect
import calendar
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Item, PriceEntry


def period_of(d: date) -> int:
    return 1 if d.day <= 10 else 2 if d.day <= 20 else 3


def period_range(year: int, month: int, period: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    start_day, end_day = {1: (1, 10), 2: (11, 20), 3: (21, last)}[period]
    return date(year, month, start_day), date(year, month, end_day)


def month_bounds(month: str) -> tuple[date, date]:
    y, m = (int(x) for x in month.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def days_in(month: str) -> list[date]:
    start, end = month_bounds(month)
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _effective(entries: list[tuple[float, str]]) -> float:
    manual = [p for p, s in entries if s == "manual"]
    return mean(manual) if manual else mean(p for p, _ in entries)


class PriceBook:
    """Loads all price entries up to `until` once and answers price lookups from memory."""

    def __init__(self, db: Session, outlet_id: int, until: date, items: list[Item] | None = None):
        if items is None:
            items = list(db.scalars(select(Item).where(Item.outlet_id == outlet_id)))
        self.items = {i.id: i for i in items}
        rows = db.execute(
            select(PriceEntry.item_id, PriceEntry.date, PriceEntry.price, PriceEntry.source).where(
                PriceEntry.outlet_id == outlet_id,
                PriceEntry.date <= until,
                PriceEntry.item_id.in_(list(self.items)),
            )
        ).all()
        by_day: dict[int, dict[date, list]] = defaultdict(lambda: defaultdict(list))
        for item_id, d, price, source in rows:
            by_day[item_id][d].append((float(price), source))
        # daily: sorted (date, effective price)
        self._daily: dict[int, tuple[list[date], list[float]]] = {}
        # weekly: sorted (period_key, effective price), period_key = (y, m, p)
        self._periods: dict[int, tuple[list[tuple], list[float]]] = {}
        for item_id, days in by_day.items():
            ds = sorted(days)
            self._daily[item_id] = (ds, [_effective(days[d]) for d in ds])
            per: dict[tuple, list] = defaultdict(list)
            for d in ds:
                per[(d.year, d.month, period_of(d))].extend(days[d])
            keys = sorted(per)
            self._periods[item_id] = (keys, [_effective(per[k]) for k in keys])
        self._month_cache: dict[tuple[int, int, int], dict] = {}

    # ---- daily -------------------------------------------------------------------------
    def daily_price(self, item_id: int, d: date) -> tuple[float, date | None]:
        """Price on date d and the date the price came from (None if never priced)."""
        ds, ps = self._daily.get(item_id, ([], []))
        i = bisect.bisect_right(ds, d) - 1
        return (ps[i], ds[i]) if i >= 0 else (0.0, None)

    # ---- weekly average ------------------------------------------------------------------
    def period_prices(self, item_id: int, year: int, month: int) -> dict:
        key = (item_id, year, month)
        if key in self._month_cache:
            return self._month_cache[key]
        keys, ps = self._periods.get(item_id, ([], []))
        out = {"periods": [], "average": 0.0}
        carry = None
        i = bisect.bisect_left(keys, (year, month, 1)) - 1
        if i >= 0:
            carry = ps[i]
        for p in (1, 2, 3):
            j = bisect.bisect_left(keys, (year, month, p))
            if j < len(keys) and keys[j] == (year, month, p):
                carry = ps[j]
                out["periods"].append({"price": ps[j], "carried": False})
            else:
                out["periods"].append({"price": carry, "carried": True})
        # An item first priced mid-month has no earlier price: backfill the leading periods with the
        # first real price so they don't drag the average to zero.
        first_real = next((x["price"] for x in out["periods"] if x["price"] is not None), 0.0)
        for x in out["periods"]:
            if x["price"] is None:
                x["price"] = first_real
            else:
                break
        out["average"] = mean(x["price"] for x in out["periods"])
        self._month_cache[key] = out
        return out

    # ---- unified -----------------------------------------------------------------------------
    def purchase_price(self, item_id: int, d: date) -> float:
        item = self.items[item_id]
        if item.pricing_mode == "daily":
            return self.daily_price(item_id, d)[0]
        return self.period_prices(item_id, d.year, d.month)["average"]

    def consumption_price(self, item_id: int, d: date) -> float:
        ratio = self.items[item_id].conversion_ratio or 1
        return self.purchase_price(item_id, d) / (ratio if ratio > 0 else 1)
