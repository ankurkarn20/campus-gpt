"""Database engine construction."""
from sqlalchemy import Engine, create_engine

from campusgpt.config import get_settings


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or get_settings().database_url, pool_pre_ping=True)
