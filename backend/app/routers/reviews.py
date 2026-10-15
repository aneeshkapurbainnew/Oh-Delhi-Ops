from collections import defaultdict
import datetime as dt
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import outlet_id
from ..db import get_db
from ..models import Review, Station
from ..services.pricing import month_bounds

router = APIRouter(prefix="/reviews", tags=["reviews"])

Status = Literal["open", "in_progress", "resolved"]
SOURCES = ["Zomato", "Swiggy", "Magic Pin", "Google", "Dine-in", "Phone / WhatsApp", "Other"]
SHIFTS = ["Lunch", "Evening", "Dinner", "Late night"]


class ReviewIn(BaseModel):
    brand: str = Field(min_length=1)
    source: str = Field(min_length=1)
    date: date
    shift: str | None = None
    review_item: str | None = None
    review_text: str | None = None
    station_id: int | None = None
    concerned_person: str | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    assigned_to: str | None = None
    status: Status = "open"
    resolution: str | None = None


class ReviewPatch(BaseModel):
    brand: str | None = None
    source: str | None = None
    date: dt.date | None = None
    shift: str | None = None
    review_item: str | None = None
    review_text: str | None = None
    station_id: int | None = None
    concerned_person: str | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    assigned_to: str | None = None
    status: Status | None = None
    resolution: str | None = None


def review_out(r: Review, stations: dict[int, str]) -> dict:
    return {
        "id": r.id,
        "brand": r.brand,
        "source": r.source,
        "date": r.date.isoformat(),
        "shift": r.shift,
        "review_item": r.review_item,
        "review_text": r.review_text,
        "station_id": r.station_id,
        "station": stations.get(r.station_id) if r.station_id else None,
        "concerned_person": r.concerned_person,
        "rating": r.rating,
        "assigned_to": r.assigned_to,
        "status": r.status,
        "resolution": r.resolution,
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
    }


def _stations(db: Session, oid: int) -> dict[int, str]:
    return {s.id: s.name for s in db.scalars(select(Station).where(Station.outlet_id == oid))}


@router.get("/options")
def options():
    return {"sources": SOURCES, "shifts": SHIFTS}


@router.get("")
def list_reviews(
    month: str | None = None,
    status: Status | None = None,
    brand: str | None = None,
    station_id: int | None = None,
    db: Session = Depends(get_db),
    oid: int = Depends(outlet_id),
):
    q = select(Review).where(Review.outlet_id == oid)
    if month:
        start, end = month_bounds(month)
        q = q.where(Review.date >= start, Review.date <= end)
    if status:
        q = q.where(Review.status == status)
    if brand:
        q = q.where(Review.brand == brand)
    if station_id:
        q = q.where(Review.station_id == station_id)
    st = _stations(db, oid)
    return [review_out(r, st) for r in db.scalars(q.order_by(Review.date.desc(), Review.id.desc()))]


@router.post("", status_code=201)
def create_review(body: ReviewIn, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    r = Review(outlet_id=oid, **body.model_dump())
    if r.status == "resolved":
        r.resolved_at = datetime.now(timezone.utc)
    db.add(r)
    db.commit()
    return review_out(r, _stations(db, oid))


@router.patch("/{review_id}")
def update_review(review_id: int, body: ReviewPatch, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    r = db.get(Review, review_id)
    if r is None or r.outlet_id != oid:
        raise HTTPException(404, "Review not found.")
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] != r.status:
        r.resolved_at = datetime.now(timezone.utc) if data["status"] == "resolved" else None
    for k, v in data.items():
        setattr(r, k, v)
    db.commit()
    return review_out(r, _stations(db, oid))


@router.delete("/{review_id}", status_code=204)
def delete_review(review_id: int, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    r = db.get(Review, review_id)
    if r is None or r.outlet_id != oid:
        raise HTTPException(404, "Review not found.")
    db.delete(r)
    db.commit()


@router.get("/trends")
def trends(month: str, db: Session = Depends(get_db), oid: int = Depends(outlet_id)):
    start, end = month_bounds(month)
    st = _stations(db, oid)
    rows = list(db.scalars(select(Review).where(Review.outlet_id == oid, Review.date >= start, Review.date <= end)))

    def group(key):
        g = defaultdict(list)
        for r in rows:
            g[key(r) or "Unassigned"].append(r)
        out = []
        for name, rs in g.items():
            rated = [r.rating for r in rs if r.rating is not None]
            out.append(
                {
                    "name": name,
                    "count": len(rs),
                    "avg_rating": round(sum(rated) / len(rated), 2) if rated else None,
                    "open": sum(1 for r in rs if r.status != "resolved"),
                    "low_ratings": sum(1 for x in rated if x <= 2),
                }
            )
        return sorted(out, key=lambda x: -x["count"])

    resolved = [r for r in rows if r.status == "resolved" and r.resolved_at and r.created_at]
    hours = [(r.resolved_at - r.created_at).total_seconds() / 3600 for r in resolved]
    return {
        "total": len(rows),
        "open": sum(1 for r in rows if r.status == "open"),
        "in_progress": sum(1 for r in rows if r.status == "in_progress"),
        "resolved": sum(1 for r in rows if r.status == "resolved"),
        "avg_resolution_hours": round(sum(hours) / len(hours), 1) if hours else None,
        "by_station": group(lambda r: st.get(r.station_id)),
        "by_brand": group(lambda r: r.brand),
        "by_person": group(lambda r: r.concerned_person),
    }
