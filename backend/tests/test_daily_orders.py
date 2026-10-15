"""The daily perishables loop end to end: requisition -> plan -> WhatsApp -> receive -> distribute -> pending."""
import os

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://ohd:ohd@localhost:5432/ohd_test")
os.environ["AUTH_DISABLED"] = "true"
os.environ.setdefault("APP_SECRET", "test-secret")

from urllib.parse import unquote  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Outlet  # noqa: E402

D = "2026-10-16"


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
def w(c):
    mandi = ok(c.post("/api/vendors", json={"name": "Mandi Raju", "phone": "98765 43210"}), 201)
    eggs_v = ok(c.post("/api/vendors", json={"name": "Egg Wala"}), 201)
    onion = ok(c.post("/api/items", json=dict(name="Onion", category="vegetables", pricing_mode="daily", purchase_unit="Kg",
                                              consumption_unit="Kg", conversion_ratio=1, daily_order=True,
                                              default_vendor_id=mandi["id"])), 201)
    eggs = ok(c.post("/api/items", json=dict(name="Eggs", category="dairy", pricing_mode="daily", purchase_unit="Tray",
                                             consumption_unit="Piece", conversion_ratio=30, daily_order=True)), 201)
    indian = ok(c.post("/api/stations", json={"name": "Indian"}), 201)
    chinese = ok(c.post("/api/stations", json={"name": "Chinese", "sort": 1}), 201)
    for s in (indian, chinese):
        ok(c.put(f"/api/stations/{s['id']}/items", json={"item_ids": [onion["id"], eggs["id"]]}))
    a = ok(c.post("/api/audits", json={"date": "2026-10-14", "kind": "opening"}), 201)
    ok(c.put(f"/api/audits/{a['id']}/counts", json={"counts": [{"item_id": onion["id"], "counted_qty": 4}]}))
    return dict(mandi=mandi["id"], eggs_v=eggs_v["id"], onion=onion["id"], eggs=eggs["id"], indian=indian["id"], chinese=chinese["id"])


def test_requisitions_and_plan(c, w):
    r = ok(c.get(f"/api/requisitions?on={D}&station_id={w['indian']}"))
    assert {x["name"] for x in r["rows"]} == {"Onion", "Eggs"} and not r["orders_sent"]
    ok(c.put("/api/requisitions", json={"date": D, "station_id": w["indian"], "lines": [
        {"item_id": w["onion"], "qty": 10}, {"item_id": w["eggs"], "qty": 45}]}))
    ok(c.put("/api/requisitions", json={"date": D, "station_id": w["chinese"], "lines": [{"item_id": w["onion"], "qty": 6}]}))
    plan = {x["name"]: x for x in ok(c.get(f"/api/daily-orders/plan?on={D}"))["rows"]}
    assert plan["Onion"]["requested"] == 16 and plan["Onion"]["stock_on_hand"] == 4
    assert plan["Onion"]["default_vendor_id"] == w["mandi"]
    assert plan["Eggs"]["requested"] == 45 and plan["Eggs"]["suggested_qty"] == 2  # 45 pieces -> 1.5 trays -> 2


def test_save_plan_and_whatsapp(c, w):
    orders = ok(c.put("/api/daily-orders/plan", json={"date": D, "lines": [
        {"item_id": w["onion"], "vendor_id": w["mandi"], "qty": 12},
        {"item_id": w["eggs"], "vendor_id": w["eggs_v"], "qty": 2}]}))
    mandi = next(o for o in orders if o["vendor"] == "Mandi Raju")
    assert mandi["whatsapp_url"].startswith("https://wa.me/919876543210?text=")
    assert "1. Onion - 12 Kg" in unquote(mandi["whatsapp_url"]) and "Fri 16 Oct" in mandi["message"]
    eggv = next(o for o in orders if o["vendor"] == "Egg Wala")
    assert not eggv["has_phone"] and eggv["whatsapp_url"].startswith("https://wa.me/?text=")
    ok(c.post(f"/api/daily-orders/{mandi['id']}/sent"))
    w["mandi_order"], w["egg_order"] = mandi["id"], eggv["id"]


def test_late_change_flags_resend(c, w):
    r = ok(c.put("/api/requisitions", json={"date": D, "station_id": w["chinese"], "lines": [{"item_id": w["onion"], "qty": 8}]}))
    assert r["orders_sent"] and next(x for x in r["rows"] if x["name"] == "Onion")["late"] is True
    plan = {x["name"]: x for x in ok(c.get(f"/api/daily-orders/plan?on={D}"))["rows"]}
    assert plan["Onion"]["needs_resend"] and plan["Onion"]["requested"] == 18
    orders = ok(c.put("/api/daily-orders/plan", json={"date": D, "lines": [
        {"item_id": w["onion"], "vendor_id": w["mandi"], "qty": 14},
        {"item_id": w["eggs"], "vendor_id": w["eggs_v"], "qty": 2}]}))
    assert next(o for o in orders if o["vendor"] == "Mandi Raju")["changed_after_send"] is True


def test_receive_creates_purchase(c, w):
    assert c.post(f"/api/daily-orders/{w['mandi_order']}/receive", json={"lines": [
        {"item_id": w["onion"], "qty_received": 10}]}).status_code == 400  # rate missing
    ok(c.post(f"/api/daily-orders/{w['mandi_order']}/receive", json={"bill_no": "M-77", "lines": [
        {"item_id": w["onion"], "qty_received": 10, "rate": 30}]}))
    ok(c.post(f"/api/daily-orders/{w['egg_order']}/receive", json={"payment_status": "paid", "lines": [
        {"item_id": w["eggs"], "qty_received": 2, "rate": 180}]}))
    bills = ok(c.get(f"/api/purchases?start={D}&end={D}"))["bills"]
    assert sorted(b["total"] for b in bills) == [300, 360]
    assert next(b for b in bills if b["total"] == 300)["payment_status"] == "credit"
    # received orders are locked in the plan
    assert c.put("/api/daily-orders/plan", json={"date": D, "lines": [
        {"item_id": w["onion"], "vendor_id": w["mandi"], "qty": 1}]}).status_code == 400


def test_distribution_and_pending(c, w):
    d = ok(c.get(f"/api/distribution?on={D}&station_id={w['indian']}"))
    onion = next(r for r in d["rows"] if r["name"] == "Onion")
    assert onion["in_store"] == 14  # 4 opening + 10 received
    ok(c.put("/api/distribution", json={"date": D, "station_id": w["indian"], "lines": [
        {"item_id": w["onion"], "qty_given": 10}, {"item_id": w["eggs"], "qty_given": 45}]}))
    d = ok(c.put("/api/distribution", json={"date": D, "station_id": w["chinese"], "lines": [
        {"item_id": w["onion"], "qty_given": 4}]}))
    row = d["rows"][0]
    assert row["short"] == 4 and row["pending"] and "short-supplied (10 of 14)" in row["reason"]
    p = ok(c.get(f"/api/pending?on={D}"))
    assert len(p) == 1 and p[0]["station"] == "Chinese" and p[0]["short"] == 4
    assert ok(c.get(f"/api/pending/count?on={D}"))["count"] == 1
    # what was given became the stations' issues
    day = ok(c.get(f"/api/issues/day?on={D}&station_id={w['chinese']}"))
    assert next(r for r in day["rows"] if r["name"] == "Onion")["qty"] == 4
    summary = {s["name"]: s for s in ok(c.get(f"/api/distribution/summary?on={D}"))}
    assert summary["Indian"]["fully_given"] == 2 and summary["Chinese"]["pending"] == 1
    ok(c.post("/api/pending/dismiss", json={"requisition_ids": [p[0]["requisition_id"]], "reason": "Used cabbage instead"}))
    assert ok(c.get(f"/api/pending?on={D}")) == []


def test_supabase_storage_calls(monkeypatch):
    from app import storage
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "storage_backend", "supabase")
    monkeypatch.setattr(s, "supabase_url", "https://abc.supabase.co")
    monkeypatch.setattr(s, "supabase_service_role_key", "srk")
    calls = []

    class R:
        def __init__(self, code=200, content=b"img"):
            self.status_code, self.content, self.headers = code, content, {"content-type": "image/jpeg"}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(storage.httpx, "post", lambda url, **k: calls.append(("post", url, k["headers"])) or R())
    monkeypatch.setattr(storage.httpx, "get", lambda url, **k: calls.append(("get", url, k["headers"])) or R())
    path = storage.save_bill_photo(5, "bill.jpg", b"x", "image/jpeg")
    content, media = storage.load_bill_photo(path)
    assert calls[0][1] == f"https://abc.supabase.co/storage/v1/object/bills/{path}"
    assert calls[1][1] == f"https://abc.supabase.co/storage/v1/object/authenticated/bills/{path}"
    assert calls[0][2]["Authorization"] == "Bearer srk" and content == b"img" and media == "image/jpeg"


def test_split_across_vendors_and_groups(c, w):
    """Same item to two vendors in different quantities; next day's plan remembers the split.
    Vendors with a WhatsApp group get a share link without a number."""
    kumar = ok(c.post("/api/vendors", json={"name": "Veg Kumar", "whatsapp_group": "Kumar Veg Orders"}), 201)
    d1, d2 = "2026-10-20", "2026-10-21"
    ok(c.put("/api/requisitions", json={"date": d1, "station_id": w["indian"], "lines": [{"item_id": w["onion"], "qty": 18}]}))
    orders = ok(c.put("/api/daily-orders/plan", json={"date": d1, "lines": [
        {"item_id": w["onion"], "vendor_id": w["mandi"], "qty": 12},
        {"item_id": w["onion"], "vendor_id": kumar["id"], "qty": 6}]}))
    by = {o["vendor"]: o for o in orders}
    assert "1. Onion - 12 Kg" in by["Mandi Raju"]["message"] and "1. Onion - 6 Kg" in by["Veg Kumar"]["message"]
    assert by["Veg Kumar"]["whatsapp_group"] == "Kumar Veg Orders"
    assert by["Veg Kumar"]["whatsapp_url"].startswith("https://wa.me/?text=")
    plan = {r["name"]: r for r in ok(c.get(f"/api/daily-orders/plan?on={d1}"))["rows"]}
    assert sorted(p["qty"] for p in plan["Onion"]["planned"]) == [6, 12]
    # next day: the split is offered again (2/3 Raju, 1/3 Kumar)
    ok(c.put("/api/requisitions", json={"date": d2, "station_id": w["indian"], "lines": [{"item_id": w["onion"], "qty": 30}]}))
    nxt = {r["name"]: r for r in ok(c.get(f"/api/daily-orders/plan?on={d2}"))["rows"]}
    split = nxt["Onion"]["last_split"]
    assert [s["vendor_id"] for s in split] == [w["mandi"], kumar["id"]]
    assert split[0]["share"] == pytest.approx(0.6667, abs=1e-3)
    # one vendor delivers short, the other hasn't delivered: reason names the one still awaited
    ok(c.post(f"/api/daily-orders/{by['Mandi Raju']['id']}/receive", json={"lines": [{"item_id": w["onion"], "qty_received": 12, "rate": 30}]}))
    d = ok(c.get(f"/api/distribution?on={d1}&station_id={w['indian']}"))
    assert d["rows"][0]["in_store"] >= 12
    ok(c.put("/api/distribution", json={"date": d1, "station_id": w["indian"], "lines": [{"item_id": w["onion"], "qty_given": 12}]}))
    p = [x for x in ok(c.get(f"/api/pending?on={d1}")) if x["date"] == d1]
    assert p and p[0]["reason"] == "Not received from Veg Kumar yet"


def test_health_reports_version(c):
    assert ok(c.get("/api/health"))["version"]


def test_dry_store_items(c, w):
    """Stations also ask for dry store items: they show on the kitchen list, stay out of vendor
    orders, are handed over from store stock, and pending explains a stock shortage."""
    oil = ok(c.post("/api/items", json=dict(name="Refined Oil", category="oils", pricing_mode="weekly_avg",
                                            purchase_unit="Litre", consumption_unit="Litre", conversion_ratio=1)), 201)
    ok(c.put(f"/api/stations/{w['indian']}/items", json={"item_ids": [w["onion"], w["eggs"], oil["id"]]}))
    d = "2026-10-25"
    kitchen = {r["name"]: r for r in ok(c.get(f"/api/requisitions?on={d}&station_id={w['indian']}"))["rows"]}
    assert kitchen["Refined Oil"]["source"] == "store" and kitchen["Onion"]["source"] == "vendor"
    # buy 3 litres on the 24th, station asks for 5 on the 25th
    ok(c.post("/api/purchases", json={"vendor_id": w["mandi"], "date": "2026-10-24", "lines": [{"item_id": oil["id"], "qty": 3, "rate": 150}]}), 201)
    ok(c.put("/api/requisitions", json={"date": d, "station_id": w["indian"], "lines": [
        {"item_id": oil["id"], "qty": 5}, {"item_id": w["onion"], "qty": 4}]}))
    plan = {r["name"] for r in ok(c.get(f"/api/daily-orders/plan?on={d}"))["rows"]}
    assert plan == {"Onion"}  # dry store item never goes to a vendor
    dist = {r["name"]: r for r in ok(c.get(f"/api/distribution?on={d}&station_id={w['indian']}"))["rows"]}
    assert dist["Refined Oil"]["source"] == "store" and dist["Refined Oil"]["in_store"] >= 3
    ok(c.put("/api/distribution", json={"date": d, "station_id": w["indian"], "lines": [{"item_id": oil["id"], "qty_given": 3}]}))
    p = {x["item"]: x for x in ok(c.get(f"/api/pending?on={d}")) if x["date"] == d}
    assert p["Refined Oil"]["short"] == 2 and p["Refined Oil"]["reason"].startswith("Only 0 left in store")
    assert p["Onion"]["reason"] == "Not ordered from a vendor"
