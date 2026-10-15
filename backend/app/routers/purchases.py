from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import outlet_id
from ..db import get_db
from ..models import Item, PriceEntry, PurchaseBill, PurchaseLine, Vendor
from ..storage import load_bill_photo, save_bill_photo

router = APIRouter(prefix="/purchases", tags=["purchases"])

MAX_PHOTO_BYTES = 10 * 1024 * 1024


class LineIn(BaseModel):
    item_id: int
    qty: float = Field(gt=0)
    rate: float = Field(ge=0)


class BillIn(BaseModel):
    vendor_id: int
    date: date
    bill_no: str | None = None
    payment_status: Literal["paid", "credit", "partial"] = "paid"
    amount_paid: float | None = Field(default=None, ge=0)
    notes: str | None = None
    lines: list[LineIn] = Field(min_length=1)

    @model_validator(mode="after")
    def check_paid(self):
        if self.payment_status == "partial" and self.amount_paid is None:
            raise ValueError("Enter the amount paid for a partly paid bill.")
        return self


def _total(b: PurchaseBill) -> float:
    return round(sum(float(l.qty) * float(l.rate) for l in b.lines), 2)


def _paid(b: PurchaseBill) -> float:
    if b.payment_status == "paid":
        return _total(b)
    if b.payment_status == "credit":
        return 0.0
    return float(b.amount_paid or 0)


def bill_out(b: PurchaseBill, items: dict[int, Item] | None = None, detail: bool = False) -> dict:
    total = _total(b)
    out = {
        "id": b.id,
        "vendor_id": b.vendor_id,
        "vendor": b.vendor.name if b.vendor else None,
        "date": b.date.isoformat(),
        "bill_no": b.bill_no,
        "payment_status": b.payment_status,
        "amount_paid": _paid(b),
        "outstanding": round(total - _paid(b), 2),
        "total": total,
        "line_count": len(b.lines),
        "has_photo": bool(b.photo_path),
        "notes": b.notes,
    }
    if detail:
        out["lines"] = [
            {
                "id": l.id,
                "item_id": l.item_id,
                "item": items[l.item_id].name if items and l.item_id in items else None,
                "purchase_unit": items[l.item_id].purchase_unit if items and l.item_id in items else None,
                "qty": float(l.qty),
                "rate": float(l.rate),
                "amount": round(float(l.qty) * float(l.rate), 2),
            }
            for l in b.lines
        ]
    return out


def _load(db: Session, bill_id: int, oid: int) -> PurchaseBill:
    b = db.scalar(
        select(PurchaseBill)
        .options(selectinload(PurchaseBill.lines), selectinload(PurchaseBill.vendor))
        .where(PurchaseBill.id == bill_id, PurchaseBill.outlet_id == oid)
    )
    if b is None:
        raise HTTPException(404, f"Purchase bill {bill_id} not found.")
    return b


def _write_lines(db: Session, b: PurchaseBill, body: BillIn, oid: int):
    known = set(db.scalars(select(Item.id).where(Item.outlet_id == oid, Item.id.in_([l.item_id for l in body.lines]))))
    missing = {l.item_id for l in body.lines} - known
    if missing:
        raise HTTPException(400, f"Unknown item ids: {sorted(missing)}.")
    b.lines.clear()
    db.flush()  # cascades price entries of old lines
    for l in body.lines:
        pl = PurchaseLine(item_id=l.item_id, qty=l.qty, rate=l.rate)
        b.lines.append(pl)
        db.flush()
        # every purchase line feeds the price list
        db.add(
            PriceEntry(
                outlet_id=oid, item_id=l.item_id, date=body.date, price=l.rate, source="purchase", purchase_line_id=pl.id
            )
        )


@router.get("")
def list_bills(
    start: date,
    end: date,
    vendor_id: int | None = None,
    db: Session = Depends(get_db),
    oid: int = Depends(outlet_id),
):
    q = (
        select(PurchaseBill)
        .options(selectinload(PurchaseBill.lines), selectinload(PurchaseBill.vendor))
        .where(PurchaseBill.outlet_id == oid, PurchaseBill.date >= start, PurchaseBill.date <= end)
        .order_by(PurchaseBill.date.desc(), PurchaseBill.id.desc())
    )
    if vendor_id:
        q = q.where(PurchaseBill.vendor_id == vendor_id)
    bills = [bill_out(b) for b in db.scalars(q)]
    return {
        "bills": bills,
        "total": round(sum(b["total"] for b in bills), 2),
        "outstanding": round(sum(b["outstanding"] for b in bills), 2),
    }


@router.get("/outstanding")
def outstanding_by_vendor(db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    q = (
        select(PurchaseBill)
        .options(selectinload(PurchaseBill.lines), selectinload(PurchaseBill.vendor))
        .where(PurchaseBill.outlet_id == oid, PurchaseBill.payment_status != "paid")
    )
    by_vendor: dict[int, dict] = {}
    for b in db.scalars(q):
        o = _total(b) - _paid(b)
        if o <= 0:
            continue
        v = by_vendor.setdefault(b.vendor_id, {"vendor_id": b.vendor_id, "vendor": b.vendor.name, "outstanding": 0.0, "bills": 0})
        v["outstanding"] = round(v["outstanding"] + o, 2)
        v["bills"] += 1
    return sorted(by_vendor.values(), key=lambda x: -x["outstanding"])


@router.post("", status_code=201)
def create_bill(body: BillIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    if db.get(Vendor, body.vendor_id) is None:
        raise HTTPException(400, "Choose a vendor.")
    b = PurchaseBill(
        outlet_id=oid,
        vendor_id=body.vendor_id,
        date=body.date,
        bill_no=body.bill_no or None,
        payment_status=body.payment_status,
        amount_paid=body.amount_paid or 0,
        notes=body.notes,
    )
    db.add(b)
    db.flush()
    _write_lines(db, b, body, oid)
    db.commit()
    return get_bill(b.id, db, oid)


@router.get("/{bill_id}")
def get_bill(bill_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    b = _load(db, bill_id, oid)
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_([l.item_id for l in b.lines])))}
    return bill_out(b, items, detail=True)


@router.put("/{bill_id}")
def update_bill(bill_id: int, body: BillIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    b = _load(db, bill_id, oid)
    b.vendor_id, b.date, b.bill_no = body.vendor_id, body.date, body.bill_no or None
    b.payment_status, b.amount_paid, b.notes = body.payment_status, body.amount_paid or 0, body.notes
    _write_lines(db, b, body, oid)
    db.commit()
    db.expire_all()
    return get_bill(b.id, db, oid)


@router.delete("/{bill_id}", status_code=204)
def delete_bill(bill_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    b = _load(db, bill_id, oid)
    db.delete(b)
    db.commit()


@router.post("/{bill_id}/photo")
async def upload_photo(
    bill_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), oid: int = Depends(outlet_id)
):
    b = _load(db, bill_id, oid)
    if not (file.content_type or "").startswith(("image/", "application/pdf")):
        raise HTTPException(400, "Upload a photo (JPG, PNG, HEIC) or a PDF of the bill.")
    content = await file.read()
    if len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(400, "The bill photo must be under 10 MB.")
    b.photo_path = save_bill_photo(b.id, file.filename or "bill.jpg", content, file.content_type or "")
    db.commit()
    return {"has_photo": True}


@router.get("/{bill_id}/photo")
def get_photo(bill_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    """Streams the bill photo; only signed-in users reach this (router-level auth)."""
    b = _load(db, bill_id, oid)
    if not b.photo_path:
        raise HTTPException(404, "This bill has no photo.")
    try:
        content, media = load_bill_photo(b.photo_path)
    except FileNotFoundError as e:
        raise HTTPException(404, "The photo file is missing from storage.") from e
    return Response(content, media_type=media, headers={"Cache-Control": "private, max-age=3600"})
