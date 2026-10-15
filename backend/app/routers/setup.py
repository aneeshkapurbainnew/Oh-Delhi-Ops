from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import outlet_id
from ..db import get_db
from ..models import Channel, ExpenseCategory, Item, Setting, Staff, Station, StationItem, Vendor

router = APIRouter(tags=["setup"])


def _get(db: Session, model, id_: int, oid: int):
    obj = db.get(model, id_)
    if obj is None or getattr(obj, "outlet_id", oid) != oid:
        raise HTTPException(404, f"{model.__name__} {id_} not found.")
    return obj


def _commit(db: Session, what: str):
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, f"{what} already exists.") from e


# ---------- items ----------------------------------------------------------------------------
class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=80)
    pricing_mode: Literal["weekly_avg", "daily"]
    purchase_unit: str = Field(min_length=1)
    consumption_unit: str = Field(min_length=1)
    conversion_ratio: float = Field(gt=0, default=1)
    active: bool = True
    daily_order: bool = False
    default_vendor_id: int | None = None


class ItemPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    pricing_mode: Literal["weekly_avg", "daily"] | None = None
    purchase_unit: str | None = None
    consumption_unit: str | None = None
    conversion_ratio: float | None = Field(default=None, gt=0)
    active: bool | None = None
    daily_order: bool | None = None
    default_vendor_id: int | None = None


def item_out(i: Item) -> dict:
    return {
        "id": i.id,
        "name": i.name,
        "category": i.category,
        "pricing_mode": i.pricing_mode,
        "purchase_unit": i.purchase_unit,
        "consumption_unit": i.consumption_unit,
        "conversion_ratio": i.conversion_ratio,
        "active": i.active,
        "daily_order": i.daily_order,
        "default_vendor_id": i.default_vendor_id,
    }


@router.get("/items")
def list_items(include_inactive: bool = False, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    q = select(Item).where(Item.outlet_id == oid)
    if not include_inactive:
        q = q.where(Item.active.is_(True))
    return [item_out(i) for i in db.scalars(q.order_by(Item.category, Item.name))]


@router.post("/items", status_code=201)
def create_item(body: ItemIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    item = Item(outlet_id=oid, **body.model_dump())
    item.category = item.category.strip().upper().replace(" ", "_")
    db.add(item)
    _commit(db, f"An item named {body.name}")
    return item_out(item)


@router.patch("/items/{item_id}")
def update_item(item_id: int, body: ItemPatch, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    item = _get(db, Item, item_id, oid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(item, k, v.strip().upper().replace(" ", "_") if k == "category" else v)
    _commit(db, f"An item named {body.name}")
    return item_out(item)


@router.get("/categories")
def categories(db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    return list(db.scalars(select(Item.category).where(Item.outlet_id == oid).distinct().order_by(Item.category)))


# ---------- stations --------------------------------------------------------------------------
class StationIn(BaseModel):
    name: str
    kind: Literal["kitchen", "staff", "packaging", "daily_items"] = "kitchen"
    sort: int = 0
    active: bool = True


class StationPatch(BaseModel):
    name: str | None = None
    kind: Literal["kitchen", "staff", "packaging", "daily_items"] | None = None
    sort: int | None = None
    active: bool | None = None


def station_out(s: Station, n_items: int = 0) -> dict:
    return {"id": s.id, "name": s.name, "kind": s.kind, "sort": s.sort, "active": s.active, "item_count": n_items}


@router.get("/stations")
def list_stations(db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    counts = dict(db.execute(select(StationItem.station_id, func.count()).group_by(StationItem.station_id)).all())
    return [
        station_out(s, counts.get(s.id, 0))
        for s in db.scalars(select(Station).where(Station.outlet_id == oid).order_by(Station.sort, Station.id))
    ]


@router.post("/stations", status_code=201)
def create_station(body: StationIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    s = Station(outlet_id=oid, **body.model_dump())
    db.add(s)
    db.commit()
    return station_out(s)


@router.patch("/stations/{station_id}")
def update_station(station_id: int, body: StationPatch, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    s = _get(db, Station, station_id, oid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    db.commit()
    return station_out(s)


@router.get("/stations/{station_id}/items")
def station_items(station_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    _get(db, Station, station_id, oid)
    rows = db.execute(
        select(Item)
        .join(StationItem, StationItem.item_id == Item.id)
        .where(StationItem.station_id == station_id)
        .order_by(StationItem.sort, Item.name)
    ).scalars()
    return [item_out(i) for i in rows]


class StationItemsIn(BaseModel):
    item_ids: list[int]


@router.put("/stations/{station_id}/items")
def set_station_items(
    station_id: int, body: StationItemsIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)
):
    _get(db, Station, station_id, oid)
    db.execute(delete(StationItem).where(StationItem.station_id == station_id))
    seen = set()
    for n, iid in enumerate(body.item_ids):
        if iid not in seen:
            seen.add(iid)
            db.add(StationItem(station_id=station_id, item_id=iid, sort=n))
    db.commit()
    return {"station_id": station_id, "item_count": len(seen)}


# ---------- simple lists: vendors, channels, expense categories, staff ------------------------
class VendorIn(BaseModel):
    name: str = Field(min_length=1)
    phone: str | None = None
    whatsapp_group: str | None = None
    active: bool = True


class ChannelIn(BaseModel):
    platform: str = Field(min_length=1)
    brand: str = Field(min_length=1)
    kinds: list[Literal["discount", "delivery", "ads"]] = ["discount", "delivery", "ads"]
    sort: int = 0
    active: bool = True


class NamedIn(BaseModel):
    name: str = Field(min_length=1)
    active: bool = True


def vendor_out(v: Vendor) -> dict:
    return {"id": v.id, "name": v.name, "phone": v.phone, "whatsapp_group": v.whatsapp_group, "active": v.active}


def channel_out(c: Channel) -> dict:
    return {
        "id": c.id,
        "platform": c.platform,
        "brand": c.brand,
        "kinds": [k for k in c.kinds.split(",") if k],
        "sort": c.sort,
        "active": c.active,
    }


@router.get("/vendors")
def list_vendors(db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    return [vendor_out(v) for v in db.scalars(select(Vendor).where(Vendor.outlet_id == oid).order_by(Vendor.name))]


@router.post("/vendors", status_code=201)
def create_vendor(body: VendorIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    v = Vendor(outlet_id=oid, **body.model_dump())
    db.add(v)
    db.commit()
    return vendor_out(v)


@router.patch("/vendors/{vendor_id}")
def update_vendor(vendor_id: int, body: VendorIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    v = _get(db, Vendor, vendor_id, oid)
    for k, val in body.model_dump().items():
        setattr(v, k, val)
    db.commit()
    return vendor_out(v)


@router.get("/channels")
def list_channels(db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    q = select(Channel).where(Channel.outlet_id == oid).order_by(Channel.sort, Channel.id)
    return [channel_out(c) for c in db.scalars(q)]


@router.post("/channels", status_code=201)
def create_channel(body: ChannelIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    d = body.model_dump()
    d["kinds"] = ",".join(d["kinds"])
    c = Channel(outlet_id=oid, **d)
    db.add(c)
    db.commit()
    return channel_out(c)


@router.patch("/channels/{channel_id}")
def update_channel(channel_id: int, body: ChannelIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    c = _get(db, Channel, channel_id, oid)
    d = body.model_dump()
    d["kinds"] = ",".join(d["kinds"])
    for k, v in d.items():
        setattr(c, k, v)
    db.commit()
    return channel_out(c)


@router.get("/brands")
def brands(db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    """Brands for the review form: every brand that appears on a sales platform channel."""
    q = select(Channel.brand).where(Channel.outlet_id == oid, Channel.kinds.contains("discount")).distinct()
    return sorted(db.scalars(q))


@router.get("/expense-categories")
def list_expense_categories(db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    q = select(ExpenseCategory).where(ExpenseCategory.outlet_id == oid).order_by(ExpenseCategory.sort)
    return [{"id": c.id, "name": c.name, "active": c.active} for c in db.scalars(q)]


@router.post("/expense-categories", status_code=201)
def create_expense_category(body: NamedIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    n = db.scalar(select(func.count()).select_from(ExpenseCategory).where(ExpenseCategory.outlet_id == oid))
    c = ExpenseCategory(outlet_id=oid, sort=n, **body.model_dump())
    db.add(c)
    db.commit()
    return {"id": c.id, "name": c.name, "active": c.active}


@router.patch("/expense-categories/{cat_id}")
def update_expense_category(cat_id: int, body: NamedIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    c = _get(db, ExpenseCategory, cat_id, oid)
    c.name, c.active = body.name, body.active
    db.commit()
    return {"id": c.id, "name": c.name, "active": c.active}


@router.get("/staff")
def list_staff(db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    q = select(Staff).where(Staff.outlet_id == oid).order_by(Staff.name)
    return [{"id": s.id, "name": s.name, "active": s.active} for s in db.scalars(q)]


@router.post("/staff", status_code=201)
def create_staff(body: NamedIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    s = Staff(outlet_id=oid, **body.model_dump())
    db.add(s)
    db.commit()
    return {"id": s.id, "name": s.name, "active": s.active}


@router.patch("/staff/{staff_id}")
def update_staff(staff_id: int, body: NamedIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    s = _get(db, Staff, staff_id, oid)
    s.name, s.active = body.name, body.active
    db.commit()
    return {"id": s.id, "name": s.name, "active": s.active}


# ---------- settings -------------------------------------------------------------------------
DEFAULT_SETTINGS = {"variance_threshold_pct": "2", "outlet_name": "Oh Delhi"}


@router.get("/settings")
def get_settings_(db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    stored = {s.key: s.value for s in db.scalars(select(Setting).where(Setting.outlet_id == oid))}
    return DEFAULT_SETTINGS | stored


@router.put("/settings")
def put_settings(body: dict[str, str], db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    for k, v in body.items():
        if k not in DEFAULT_SETTINGS:
            raise HTTPException(400, f"Unknown setting {k}.")
        if k == "variance_threshold_pct":
            try:
                if float(v) <= 0:
                    raise ValueError
            except ValueError as e:
                raise HTTPException(400, "Variance threshold must be a positive number.") from e
        row = db.get(Setting, (oid, k))
        if row:
            row.value = str(v)
        else:
            db.add(Setting(outlet_id=oid, key=k, value=str(v)))
    db.commit()
    return get_settings_(db, oid)
