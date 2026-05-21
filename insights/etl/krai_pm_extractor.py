"""
KRAI PM extractor — reads warranty/lifetime data from the KRAI PostgreSQL source.

READ-ONLY: only SELECT statements against the `krai_pm` schema (service_tickets,
part_lifetimes, part_warranty_events, device_lifecycle) plus migration-038 cross-
system columns (radix_device_id, device_serial, part_number_variants).

Skeleton for the `extractors` todo — to be implemented in Phase 1 after bootstrap.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import text

from insights.core.config import get_settings
from insights.core.db import krai_pg_engine
from insights.core.logging import get_logger

logger = get_logger(__name__)


def fetch_part_warranty_events(limit: int | None = None) -> Iterator[dict[str, Any]]:
    """Yield rows from krai_pm.part_warranty_events (read-only).

    TODO(extractors): finalise column selection and join to device_lifecycle for
    serials; feed insights.warranty_claims in Phase 3.
    """
    schema = get_settings().krai_pg_schema
    sql = f"SELECT * FROM {schema}.part_warranty_events"
    if limit:
        sql += " LIMIT :lim"
    with krai_pg_engine().connect() as conn:
        result = conn.execute(text(sql), {"lim": limit} if limit else {})
        for row in result.mappings():
            yield dict(row)


def ping() -> bool:
    """Lightweight connectivity check against the KRAI PostgreSQL source."""
    with krai_pg_engine().connect() as conn:
        return conn.execute(text("SELECT 1")).scalar() == 1
