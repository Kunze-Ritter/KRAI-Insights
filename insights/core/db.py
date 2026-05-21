"""
SQLAlchemy engine factories.

- `insights_engine()`  -> read/write, the only DB we own.
- `krai_pg_engine()`   -> READ-ONLY source (KRAI PostgreSQL, krai_pm schema).
- `fleetmgmt_engine()` -> READ-ONLY source (FleetMgmt MSSQL via pyodbc).

Source engines are configured for read-only use by convention: extractors must
issue SELECT-only statements. We never run DDL/DML against the sources.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from insights.core.config import get_settings


@lru_cache(maxsize=1)
def insights_engine() -> Engine:
    """Engine for the Insights PostgreSQL (read/write)."""
    return create_engine(
        get_settings().insights_sqlalchemy_url,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def krai_pg_engine() -> Engine:
    """Engine for the KRAI PostgreSQL source (treat as READ-ONLY)."""
    return create_engine(
        get_settings().krai_pg_sqlalchemy_url,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def fleetmgmt_engine() -> Engine:
    """Engine for the FleetMgmt MSSQL source (treat as READ-ONLY)."""
    return create_engine(
        get_settings().fleetmgmt_sqlalchemy_url,
        pool_pre_ping=True,
        future=True,
    )
