from functools import lru_cache

from app.config import get_settings
from app.store.memory_store import InMemoryStore, Store
from app.store.postgres_store import PostgresStore

__all__ = ["InMemoryStore", "PostgresStore", "Store", "get_store"]


@lru_cache
def get_store() -> Store:
    """`PostgresStore` when `settings.database_url` is set, else `InMemoryStore`.

    Tests never set `DATABASE_URL`, so the entire free/stub-backed test suite keeps
    exercising `InMemoryStore` exactly as before this file existed.
    """
    if get_settings().database_url:
        return PostgresStore()
    return InMemoryStore()
