"""Load the template (items, units, conversions, starting prices, stations, channels, expense
categories, staff) extracted from October2026InventorySheet.xlsx.

    python -m app.seed.load --price-date 2026-11-01

Safe to re-run: existing rows (matched by name) are left alone.
"""
import argparse
import json
from datetime import date
from pathlib import Path

from sqlalchemy import select

from ..db import SessionLocal
from ..models import Channel, ExpenseCategory, Item, Outlet, PriceEntry, Setting, Staff, Station, StationItem

DAILY_ORDER_CATEGORIES = {"VEGETABLES", "RAW_MEATS"}
DAILY_ORDER_ITEMS = {"SOYA CHAAP", "CURD ( OPEN )", "SEPARATA CURD", "PANEER", "KHOYA", "EGGS TRAY", "NOODLES", "RUMALI ROTI"}

STATION_KINDS = {"Indian": "kitchen", "Tandoor": "kitchen", "Chinese": "kitchen", "Conti": "kitchen",
                 "Staff": "staff", "Packaging": "packaging", "Daily Items": "daily_items"}


def load(price_date: date, outlet_id: int = 1, outlet_name: str = "Oh Delhi") -> dict:
    data = json.loads((Path(__file__).parent / "template.json").read_text())
    db = SessionLocal()
    stats = dict(items=0, prices=0, stations=0, channels=0, expense_categories=0, staff=0)
    try:
        if db.get(Outlet, outlet_id) is None:
            db.add(Outlet(id=outlet_id, name=outlet_name))
            db.add(Setting(outlet_id=outlet_id, key="outlet_name", value=outlet_name))
            db.flush()
        existing = {i.name.upper(): i for i in db.scalars(select(Item).where(Item.outlet_id == outlet_id))}
        for it in data["items"]:
            if it["name"].upper() in existing:
                continue
            item = Item(outlet_id=outlet_id, name=it["name"], category=it["category"], pricing_mode=it["pricing_mode"],
                        purchase_unit=it["purchase_unit"], consumption_unit=it["consumption_unit"],
                        conversion_ratio=it["conversion_ratio"],
                        daily_order=it["category"] in DAILY_ORDER_CATEGORIES or it["name"].upper() in DAILY_ORDER_ITEMS)
            db.add(item)
            db.flush()
            existing[item.name.upper()] = item
            stats["items"] += 1
            if it["start_price"] > 0:
                db.add(PriceEntry(outlet_id=outlet_id, item_id=item.id, date=price_date, price=it["start_price"], source="manual"))
                stats["prices"] += 1
        stations = {s.name: s for s in db.scalars(select(Station).where(Station.outlet_id == outlet_id))}
        for n, (name, item_names) in enumerate(data["stations"].items()):
            if name in stations:
                continue
            st = Station(outlet_id=outlet_id, name=name, kind=STATION_KINDS.get(name, "kitchen"), sort=n)
            db.add(st)
            db.flush()
            stats["stations"] += 1
            for k, iname in enumerate(item_names):
                db.add(StationItem(station_id=st.id, item_id=existing[iname.upper()].id, sort=k))
        have = {(c.platform, c.brand) for c in db.scalars(select(Channel).where(Channel.outlet_id == outlet_id))}
        for n, c in enumerate(data["channels"]):
            if (c["platform"], c["brand"]) not in have:
                db.add(Channel(outlet_id=outlet_id, platform=c["platform"], brand=c["brand"], kinds=",".join(c["kinds"]), sort=n))
                stats["channels"] += 1
        have = {c.name for c in db.scalars(select(ExpenseCategory).where(ExpenseCategory.outlet_id == outlet_id))}
        for n, name in enumerate(data["expense_categories"]):
            if name not in have:
                db.add(ExpenseCategory(outlet_id=outlet_id, name=name, sort=n))
                stats["expense_categories"] += 1
        have = {s.name for s in db.scalars(select(Staff).where(Staff.outlet_id == outlet_id))}
        for name in data["staff"]:
            if name not in have:
                db.add(Staff(outlet_id=outlet_id, name=name))
                stats["staff"] += 1
        db.commit()
    finally:
        db.close()
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--price-date", default=date.today().replace(day=1).isoformat(),
                    help="Date the template's starting prices take effect (default: 1st of this month)")
    args = ap.parse_args()
    print(load(date.fromisoformat(args.price_date)))
