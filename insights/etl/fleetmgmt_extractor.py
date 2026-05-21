"""
FleetMgmt extractor — reads device/counter/cartridge data from the MSSQL source.

READ-ONLY: only SELECT statements. ~62M rows, 11.8k active devices, 11 years of
counter history. Source-ID-keyed for idempotent re-runs.

Skeleton for the `extractors` todo — to be implemented in Phase 1 after bootstrap.
Key tables (per docs/fleetmgmt_data_insights.md in KRAI): ACCDEVICES (Id, SerialNo,
Location with embedded internal id, VendorId, ...) and the counter/toner-event tables.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import text

from insights.core.db import fleetmgmt_engine
from insights.core.logging import get_logger

logger = get_logger(__name__)


def fetch_devices(limit: int | None = None) -> Iterator[dict[str, Any]]:
    """Yield raw device rows from FleetMgmt.ACCDEVICES (read-only).

    TODO(extractors): finalise column selection + internal-id regex extraction
    from the Location field; stream in batches for the full 62M-row history.
    """
    sql = "SELECT TOP (:lim) * FROM ACCDEVICES" if limit else "SELECT * FROM ACCDEVICES"
    with fleetmgmt_engine().connect() as conn:
        result = conn.execute(text(sql), {"lim": limit} if limit else {})
        for row in result.mappings():
            yield dict(row)


def ping() -> bool:
    """Lightweight connectivity check against FleetMgmt MSSQL."""
    with fleetmgmt_engine().connect() as conn:
        return conn.execute(text("SELECT 1")).scalar() == 1
