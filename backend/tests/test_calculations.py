"""End-to-end check of the calculation rules against a scenario worked out by hand.

Run against a throwaway Postgres database:
    TEST_DATABASE_URL=postgresql+psycopg://ohd:ohd@localhost:5432/ohd_test pytest -q
"""
import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://ohd:ohd@localhost:5432/ohd_test"
)
os.environ["AUTH_DISABLED"] = "true"
os.environ.setdefault("APP_SECRET", "test-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Outlet  # noqa: E402


@pytest.fixture(scope="module")
def c():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(Outlet(id=1, name="Test"))
        db.commit()
    with TestClient(app) as client:
        yield client
    Base.metadata.drop_all(engine)


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


@pytest.fixture(scope="module")
def world(c):
    onion = ok(c.post("/api/items", json=dict(name="Onion", category="vegetables", pricing_mode="daily",
                                              purchase_unit="Kg", consumption_unit="Kg", conversion_ratio=1)), 201)
    water = ok(c.post("/api/items", json=dict(name="Mineral Water", category="drinks", pricing_mode="weekly_avg",
                                              purchase_unit="Peti", consumption_unit="Piece", conversion_ratio=12)), 201)
    indian = ok(c.post("/api/stations", json=dict(name="Indian", kind="kitchen")), 201)
    chinese = ok(c.post("/api/stations", json=dict(name="Chinese", kind="kitchen")), 201)
    daily = ok(c.post("/api/stations", json=dict(name="Daily Items", kind="daily_items")), 201)
    vendor = ok(c.post("/api/vendors", json=dict(name="Azadpur Mandi")), 201)
    o, w = onion["id"], water["id"]

    # prices
    ok(c.put("/api/prices/daily", json=dict(date="2026-10-01", prices=[dict(item_id=o, price=30)])))
    ok(c.put("/api/prices/weekly", json=dict(month="2026-10", period=1, prices=[dict(item_id=w, price=120)])))
    # opening count 30 Sep
    a0 = ok(c.post("/api/audits", json=dict(date="2026-09-30", kind="opening")), 201)
    ok(c.put(f"/api/audits/{a0['id']}/counts", json=dict(counts=[dict(item_id=o, counted_qty=10), dict(item_id=w, counted_qty=24)])))
    ok(c.post(f"/api/audits/{a0['id']}/close"))
    # purchases: onion 50 kg @40 on 5 Oct (credit), water 2 peti @132 on 15 Oct (partial)
    ok(c.post("/api/purchases", json=dict(vendor_id=vendor["id"], date="2026-10-05", payment_status="credit",
                                          lines=[dict(item_id=o, qty=50, rate=40)])), 201)
    ok(c.post("/api/purchases", json=dict(vendor_id=vendor["id"], date="2026-10-15", payment_status="partial",
                                          amount_paid=100, lines=[dict(item_id=w, qty=2, rate=132)])), 201)
    # manual price on 5 Oct overrides the purchase rate that day
    ok(c.put("/api/prices/daily", json=dict(date="2026-10-05", prices=[dict(item_id=o, price=35)])))
    # issues
    ok(c.put("/api/issues/day", json=dict(date="2026-10-03", station_id=indian["id"], lines=[dict(item_id=o, qty=5)])))
    ok(c.put("/api/issues/day", json=dict(date="2026-10-06", station_id=chinese["id"], lines=[dict(item_id=o, qty=10)])))
    ok(c.put("/api/issues/day", json=dict(date="2026-10-16", station_id=daily["id"], lines=[dict(item_id=w, qty=30)])))
    # cooked-food wastage in rupees: does not move raw stock, adds to COGS
    ok(c.post("/api/wastage", json=dict(date="2026-10-07", dish="Dal Makhani", qty=2, unit="plates", value=70,
                                        station_id=indian["id"], reason="Over-prepared / leftover")), 201)
    ok(c.post("/api/wastage", json=dict(date="2026-10-08", dish="Veg Manchurian", value=35, reason="Returned by customer")), 201)
    return dict(o=o, w=w, indian=indian["id"], chinese=chinese["id"], daily=daily["id"], vendor=vendor["id"])


def row(rows, item_id):
    return next(r for r in rows if r["item_id"] == item_id)


def test_daily_price_rules(c, world):
    p = {r["item_id"]: r for r in ok(c.get("/api/prices/daily?on=2026-10-03"))}
    assert p[world["o"]]["price"] == 30 and p[world["o"]]["carried_forward"]
    p = {r["item_id"]: r for r in ok(c.get("/api/prices/daily?on=2026-10-05"))}
    assert p[world["o"]]["price"] == 35  # manual beats purchase (40)
    assert p[world["o"]]["purchase_price"] == 40


def test_weekly_average(c, world):
    p = {r["item_id"]: r for r in ok(c.get("/api/prices/weekly?month=2026-10"))}[world["w"]]
    assert [x["price"] for x in p["periods"]] == [120, 132, 132]
    assert p["periods"][2]["carried"] is True
    assert p["average"] == 128
    assert p["consumption_price"] == pytest.approx(10.67, abs=0.01)


def test_spot_audit_and_threshold(c, world):
    a = ok(c.post("/api/audits", json=dict(date="2026-10-10", kind="spot")), 201)
    d = ok(c.put(f"/api/audits/{a['id']}/counts", json=dict(counts=[dict(item_id=world["o"], counted_qty=44.5)])))
    r = row(d["rows"], world["o"])
    # expected = 10 opening + 50 purchased - 15 issued = 45; wastage does not touch raw stock
    assert (r["opening"], r["purchased"], r["issued"], r["ideal"]) == (10, 50, 15, 45)
    assert r["variance"] == 0.5 and r["variance_pct"] == pytest.approx(1.11, abs=0.01)  # 0.5 / 45 expected
    assert r["flagged"] is False  # under 2%
    assert r["variance_value"] == 17.5  # 0.5 kg x price on 10 Oct (carried from 5 Oct)
    w = row(d["rows"], world["w"])
    assert w["counted"] is None and w["variance"] is None and w["ideal"] == 24
    world["spot"] = a["id"]


def test_month_end_requires_closed_audits(c, world):
    me = ok(c.post("/api/audits", json=dict(date="2026-10-31", kind="month_end")), 201)
    ok(c.put(f"/api/audits/{me['id']}/counts", json=dict(counts=[dict(item_id=world["o"], counted_qty=40), dict(item_id=world["w"], counted_qty=15)])))
    r = c.post(f"/api/audits/{me['id']}/close")
    assert r.status_code == 400 and "10 Oct" in r.json()["detail"]
    assert c.post("/api/audits", json=dict(date="2026-10-20", kind="month_end")).status_code == 409
    ok(c.post(f"/api/audits/{world['spot']}/close"))
    ok(c.post(f"/api/audits/{me['id']}/close"))
    d = ok(c.get(f"/api/audits/{me['id']}"))
    o, w = row(d["rows"], world["o"]), row(d["rows"], world["w"])
    assert o["opening"] == 44.5 and o["ideal"] == 44.5 and o["variance"] == 4.5 and o["flagged"]
    assert o["variance_pct"] == pytest.approx(10.11, abs=0.01)
    # water: 24 carried (not counted on 10 Oct) + 24 bought - 30 issued = 18 expected, 15 counted
    assert (w["opening"], w["purchased"], w["ideal"], w["variance"]) == (24, 24, 18, 3)
    assert w["variance_pct"] == pytest.approx(16.67, abs=0.01) and w["flagged"]


def test_month_end_summary(c, world):
    m = ok(c.get("/api/audits-monthly?month=2026-10"))
    o = row(m["rows"], world["o"])
    assert (o["opening"], o["purchased"], o["issued"], o["ideal"], o["counted"]) == (10, 50, 15, 45, 40)
    assert o["variance"] == 5 and o["variance_pct"] == pytest.approx(11.11, abs=0.01) and o["variance_value"] == 175


def test_pnl(c, world):
    ok(c.put("/api/sales", json=dict(rows=[dict(date="2026-10-01", gross_sale=10000, complimentary=500, net_sales=9000)])))
    ok(c.put("/api/monthly-inputs/2026-10", json=dict(wage_cost=3000)))
    cats = ok(c.post("/api/expense-categories", json=dict(name="Gas Cost")), 201)
    ok(c.put("/api/expenses", json=dict(cells=[dict(date="2026-10-02", row_id=cats["id"], amount=100)])))
    ch = ok(c.post("/api/channels", json=dict(platform="Swiggy", brand="Oh Delhi")), 201)
    ok(c.put("/api/channel-costs?kind=ads", json=dict(cells=[dict(date="2026-10-02", row_id=ch["id"], amount=200)])))
    ok(c.put("/api/channel-costs?kind=delivery", json=dict(cells=[dict(date="2026-10-02", row_id=ch["id"], amount=50)])))
    p = ok(c.get("/api/reports/pnl?month=2026-10"))
    L = {ln["key"]: ln["value"] for ln in p["lines"]}
    # onion 5x30 + 10x35 = 500 (kitchen); water 30 x 128/12 = 320 (daily items)
    assert L["consumption"] == pytest.approx(820, abs=0.01)
    assert L["wastage"] == 105  # all cooked-food wastage counts, 70 + 35
    assert L["cogs"] == pytest.approx(925, abs=0.01)
    assert L["gross_profit"] == pytest.approx(8075, abs=0.01)
    assert L["restaurant_margin"] == pytest.approx(5075, abs=0.01)
    assert L["ebitda"] == pytest.approx(4725, abs=0.01)
    w = ok(c.get("/api/wastage?month=2026-10"))
    assert w["total"] == 105 and w["by_station"][0] == {"name": "Indian", "value": 70}
    assert p["ratios"]["food_cost_pct"] == pytest.approx(5.56, abs=0.01)
    pdf = c.get("/api/reports/pnl.pdf?month=2026-10")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_min_par_stock(c, world):
    ok(c.put("/api/issues/day", json=dict(date="2026-11-02", station_id=world["daily"], lines=[dict(item_id=world["w"], qty=5)])))
    lv = {r["item_id"]: r for r in ok(c.get("/api/stock/levels?on=2026-11-15"))}
    o, w = lv[world["o"]], lv[world["w"]]
    assert (o["min_stock"], o["par_stock"], o["estimated_stock"], o["status"]) == (4.68, 5, 40, "ok")
    assert (w["min_stock"], w["par_stock"], w["estimated_stock"], w["status"]) == (9.37, 11, 10, "order")
    assert w["suggested_qty"] == 1 and w["suggested_purchase_qty"] == 1


def test_credit_outstanding(c, world):
    out = ok(c.get("/api/purchases/outstanding"))
    assert out[0]["outstanding"] == pytest.approx(2000 + 264 - 100)


def test_editing_purchase_updates_prices_and_stock(c, world):
    bills = ok(c.get("/api/purchases?start=2026-10-15&end=2026-10-15"))["bills"]
    b = ok(c.get(f"/api/purchases/{bills[0]['id']}"))
    ok(c.put(f"/api/purchases/{b['id']}", json=dict(vendor_id=world["vendor"], date="2026-10-15", payment_status="paid",
                                                   lines=[dict(item_id=world["w"], qty=3, rate=150)])))
    p = {r["item_id"]: r for r in ok(c.get("/api/prices/weekly?month=2026-10"))}[world["w"]]
    assert [x["price"] for x in p["periods"]] == [120, 150, 150]
    m = ok(c.get("/api/audits-monthly?month=2026-10"))
    assert row(m["rows"], world["w"])["purchased"] == 36


def test_reviews_flow(c, world):
    r = ok(c.post("/api/reviews", json=dict(brand="Oh Delhi", source="Zomato", date="2026-10-12", rating=2,
                                            station_id=world["indian"], review_item="Dal Makhani", assigned_to="Rahim")), 201)
    ok(c.patch(f"/api/reviews/{r['id']}", json=dict(status="resolved", resolution="Recipe re-briefed")))
    t = ok(c.get("/api/reviews/trends?month=2026-10"))
    assert t["resolved"] == 1 and t["by_station"][0]["name"] == "Indian" and t["by_station"][0]["low_ratings"] == 1
