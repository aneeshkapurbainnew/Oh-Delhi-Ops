"""Safety net: the tests DROP and recreate every table, so refuse to run against anything
that doesn't look like a throwaway test database (name must end in _test)."""
import os

from sqlalchemy.engine import make_url

_url = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://ohd:ohd@localhost:5432/ohd_test")
if not (make_url(_url).database or "").endswith("_test"):
    raise SystemExit(
        f"Refusing to run tests: TEST_DATABASE_URL points at '{make_url(_url).database}'. "
        "Tests drop all tables; use a database whose name ends in _test."
    )
