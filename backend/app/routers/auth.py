from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import (
    check_throttle,
    clear_failures,
    clear_session,
    hash_password,
    issue_session,
    record_failure,
    require_user,
    verify_password,
)
from ..db import get_db
from ..models import User

router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])

MIN_PASSWORD = 8


class LoginIn(BaseModel):
    email: str
    password: str


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD)


class UserIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=MIN_PASSWORD)
    station_id: int | None = None


class UserPatch(BaseModel):
    name: str | None = None
    station_id: int | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=MIN_PASSWORD)  # reset by a colleague


def user_out(u: User | None) -> dict:
    if u is None:  # auth disabled
        return {"id": 0, "email": "local dev", "name": "Local dev", "active": True, "station_id": None}
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "active": u.active,
        "station_id": u.station_id,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


@router.post("/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    key = body.email.strip().lower()
    check_throttle(key)
    user = db.scalar(select(User).where(func.lower(User.email) == key))
    if user is None or not user.active or not verify_password(body.password, user.password_hash):
        record_failure(key)
        raise HTTPException(401, "Email or password is incorrect.")
    clear_failures(key)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    issue_session(response, user)
    return user_out(user)


@router.post("/logout")
def logout(response: Response):
    clear_session(response)
    return {"ok": True}


@router.get("/me")
def me(user: User | None = Depends(require_user)):
    return user_out(user)


@router.post("/password")
def change_password(
    body: PasswordIn, response: Response, user: User | None = Depends(require_user), db: Session = Depends(get_db)
):
    if user is None:
        raise HTTPException(400, "Sign-in is turned off on this server.")
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect.")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # signs out other devices
    db.commit()
    issue_session(response, user)
    return {"ok": True}


# ---- user management (any signed-in user; no roles yet) ----
@users_router.get("")
def list_users(db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.name))]


@users_router.post("", status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db)):
    u = User(
        email=body.email.strip().lower(),
        name=body.name.strip(),
        password_hash=hash_password(body.password),
        station_id=body.station_id,
    )
    db.add(u)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, f"{body.email} already has an account.") from e
    return user_out(u)


@users_router.patch("/{user_id}")
def update_user(user_id: int, body: UserPatch, db: Session = Depends(get_db), me_: User | None = Depends(require_user)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found.")
    if body.active is False and me_ is not None and me_.id == u.id:
        raise HTTPException(400, "You can't deactivate your own account.")
    if body.name is not None:
        u.name = body.name
    if "station_id" in body.model_fields_set:
        u.station_id = body.station_id
    if body.active is not None and body.active != u.active:
        u.active = body.active
        u.token_version += 1
    if body.password:
        u.password_hash = hash_password(body.password)
        u.token_version += 1
    db.commit()
    return user_out(u)
