"""
FleetMgmt extractor — reads device data from the MSSQL source (read-only).

SELECT-only. DATA PROTECTION: an explicit non-PII column whitelist (never
`SELECT *`). Customer = company name + city only (`ACCUSERS.Name`/`City` via
`ACCDEVICES.SubmitterId`); `FullName`/`EMail`/credentials are never selected.

Verified join paths (2026-05-22):
  * device -> customer: `ACCDEVICES.SubmitterId = ACCUSERS.Id` (Name = company;
    DeviceManagerId is the MSP "KunzeRitter", not the end customer).
  * device -> vendor:   `ACCDEVICES.VendorId = ACCDEVICEVENDORS.Id` (.Vendor).
  * timestamps are UTC (the MSSQL server runs on UTC; datetime2 values are UTC).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from insights.core.db import fleetmgmt_engine
from insights.core.logging import get_logger

logger = get_logger(__name__)

# "live" if it transferred data within this many days (60 covers ~9-week summer
# holidays). Configurable later via business_rules.yaml.
LIVE_THRESHOLD_DAYS = 60

# Non-PII column whitelist joined into one read.
_DEVICE_SQL = """
SELECT
    d.Id                   AS fleetmgmt_device_id,
    d.SerialNo             AS serial_no,
    d.Model                AS model_display,
    d.VendorId             AS vendor_id,
    v.Vendor               AS vendor,
    d.Location             AS location,
    d.SubmitterId          AS submitter_id,
    u.Name                 AS customer_name,
    u.City                 AS customer_city,
    d.Created              AS created,
    d.Deactivated          AS deactivated,
    d.Deleted              AS deleted,
    d.LastDataTransferDate AS last_data_transfer_at
FROM ACCDEVICES d
LEFT JOIN ACCUSERS u           ON u.Id = d.SubmitterId
LEFT JOIN ACCDEVICEVENDORS v   ON v.Id = d.VendorId
"""

# Internal id occasionally embedded in the Location field, e.g. "ID: 17484".
_INTERNAL_ID_RE = re.compile(r"\bID[:\s\-]*(\d{3,})\b", re.IGNORECASE)


def extract_internal_id(location: str | None) -> str | None:
    """Best-effort extraction of an embedded internal id from the Location text."""
    if not location:
        return None
    m = _INTERNAL_ID_RE.search(location)
    return m.group(1) if m else None


def classify_device_status(
    *,
    last_data_transfer_at: datetime | None,
    deactivated: datetime | None,
    deleted: datetime | None,
    now: datetime | None = None,
    threshold_days: int = LIVE_THRESHOLD_DAYS,
) -> tuple[str, int | None]:
    """Return (device_status, telemetry_stale_days).

    status: deleted | deactivated | never_reported | live | silent.
    Telemetry timestamps are treated as UTC (tz-naive values are assumed UTC).
    """
    if deleted is not None:
        return "deleted", None
    if deactivated is not None:
        return "deactivated", None
    if last_data_transfer_at is None:
        return "never_reported", None
    now = now or datetime.now(UTC)
    last = last_data_transfer_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    stale_days = (now - last).days
    return ("live" if stale_days <= threshold_days else "silent"), stale_days


def fetch_devices(limit: int | None = None) -> Iterator[dict[str, Any]]:
    """Yield enriched device rows (read-only), with internal_id + device_status.

    Joins customer (company + city) and vendor; never selects PII columns.
    """
    sql = _DEVICE_SQL
    params: dict[str, Any] = {}
    if limit:
        sql = sql.replace("SELECT\n", f"SELECT TOP ({int(limit)})\n", 1)
    with fleetmgmt_engine().connect() as conn:
        result = conn.execute(text(sql), params)
        now = datetime.now(UTC)
        for row in result.mappings():
            rec = dict(row)
            rec["internal_id"] = extract_internal_id(rec.get("location"))
            status, stale = classify_device_status(
                last_data_transfer_at=rec.get("last_data_transfer_at"),
                deactivated=rec.get("deactivated"),
                deleted=rec.get("deleted"),
                now=now,
            )
            rec["device_status"] = status
            rec["telemetry_stale_days"] = stale
            yield rec


def ping() -> bool:
    """Lightweight connectivity check against FleetMgmt MSSQL."""
    with fleetmgmt_engine().connect() as conn:
        return conn.execute(text("SELECT 1")).scalar() == 1
