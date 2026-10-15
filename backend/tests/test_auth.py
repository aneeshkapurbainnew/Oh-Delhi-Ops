"""Login, sessions and protected routes with the built-in auth."""
import os

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://ohd:ohd@localhost:5432/ohd_test")
os.environ["AUTH_DISABLED"] = "true"
os.environ.setdefault("APP_SECRET", "test-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password, verify_password  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Outlet, User  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(Outlet(id=1, name="Test"))
        db.add(User(email="owner@ohdelhi.in", name="Owner", password_hash=hash_password("correct horse")))
        db.commit()
    s = get_settings()
    monkeypatch.setattr(s, "auth_disabled", False)
    monkeypatch.setattr(s, "app_secret", "test-secret")
    monkeypatch.setattr(s, "cookie_secure", False)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)


def test_hashing():
    h = hash_password("abc12345")
    assert h.startswith("scrypt$") and verify_password("abc12345", h) and not verify_password("nope", h)


def test_protected_without_session(client):
    assert client.get("/api/items").status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/health").status_code == 200


def test_login_flow(client):
    assert client.post("/api/auth/login", json={"email": "owner@ohdelhi.in", "password": "wrong"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "OWNER@ohdelhi.in", "password": "correct horse"})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").json()["email"] == "owner@ohdelhi.in"
    assert client.get("/api/items").status_code == 200
    # add a colleague; deactivating them ends their session
    r = client.post("/api/users", json={"email": "mgr@ohdelhi.in", "name": "Manager", "password": "manager123"})
    assert r.status_code == 201
    other = TestClient(app)
    assert other.post("/api/auth/login", json={"email": "mgr@ohdelhi.in", "password": "manager123"}).status_code == 200
    assert other.get("/api/items").status_code == 200
    client.patch(f"/api/users/{r.json()['id']}", json={"active": False})
    assert other.get("/api/items").status_code == 401
    # password change keeps this session; old password stops working
    r = client.post("/api/auth/password", json={"current_password": "correct horse", "new_password": "battery staple"})
    assert r.status_code == 200
    assert client.get("/api/items").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/items").status_code == 401
    assert client.post("/api/auth/login", json={"email": "owner@ohdelhi.in", "password": "correct horse"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "owner@ohdelhi.in", "password": "battery staple"}).status_code == 200


def test_throttle(client):
    for _ in range(8):
        client.post("/api/auth/login", json={"email": "x@y.in", "password": "bad"})
    assert client.post("/api/auth/login", json={"email": "x@y.in", "password": "bad"}).status_code == 429
