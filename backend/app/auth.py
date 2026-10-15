"""Built-in login: scrypt password hashes, signed session cookie (httpOnly, SameSite=Lax).

No third-party auth service. The session is a short JWT signed with APP_SECRET; each request
re-checks that the user is still active and that the token version matches, so deactivating
a user or changing a password signs them out everywhere.
"""
import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

COOKIE = "ohd_session"
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        calc = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(calc, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def issue_session(response: Response, user: User) -> None:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(hours=s.session_hours)
    token = jwt.encode({"sub": str(user.id), "v": user.token_version, "exp": exp}, s.app_secret, algorithm="HS256")
    response.set_cookie(
        COOKIE, token, max_age=s.session_hours * 3600, httponly=True, secure=s.cookie_secure, samesite="lax", path="/"
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def require_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    s = get_settings()
    if s.auth_disabled:
        return None
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    try:
        payload = jwt.decode(token, s.app_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired. Sign in again.") from e
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.active or user.token_version != payload.get("v"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has ended. Sign in again.")
    return user


# --- simple login throttle: 8 failures per email per 15 minutes (per process) ---
_fails: dict[str, deque] = defaultdict(deque)
WINDOW, LIMIT = 15 * 60, 8


def check_throttle(key: str) -> None:
    q = _fails[key]
    now = time.monotonic()
    while q and now - q[0] > WINDOW:
        q.popleft()
    if len(q) >= LIMIT:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed sign-ins. Try again in 15 minutes.")


def record_failure(key: str) -> None:
    _fails[key].append(time.monotonic())


def clear_failures(key: str) -> None:
    _fails.pop(key, None)


def outlet_id() -> int:
    """Single outlet for now; phase 5 reads this from the user's selected outlet."""
    return get_settings().default_outlet_id
