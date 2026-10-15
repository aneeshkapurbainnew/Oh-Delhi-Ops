from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

_url = get_settings().database_url
# Supabase's transaction pooler (port 6543) does not support prepared statements
_connect_args = {"prepare_threshold": None} if ":6543" in _url else {}
engine = create_engine(_url, pool_pre_ping=True, pool_size=5, max_overflow=5, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
