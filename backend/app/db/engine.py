"""SQLAlchemy engine + session setup for PostgresStore.

Session-per-call, not request-scoped: `PostgresStore` (app/store/postgres_store.py) opens
a short-lived Session per method call via `session_scope()`, one transaction each. This
keeps `get_store()` a plain singleton exactly as InMemoryStore is today — no FastAPI
dependency injection threading a session through every route.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """One transaction: commits on clean exit, rolls back and re-raises on error."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
