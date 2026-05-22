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


# VBM / consumable change events. Non-PII; `CreatedBy` deliberately excluded.
_MARKER_SQL = """
SELECT
    pkId                  AS source_pkid,
    DeviceId              AS fleetmgmt_device_id,
    SerialNo              AS cartridge_serial,
    Colorant              AS colorant,
    Name                  AS marker_name,
    PageCount             AS page_count_at_event,
    lSumBW                AS sum_bw,
    lSumColor             AS sum_color,
    lDiffPageCount        AS pages_since_previous,
    lDiffSumBW            AS diff_bw,
    lDiffSumColor         AS diff_color,
    CoveragePercentIs     AS coverage_real_pct,
    CoveragePercentTarget AS oem_target_coverage_pct,
    CoveragePagesTarget   AS oem_target_pages,
    RemainingPages        AS remaining_pages,
    RemainingDays         AS remaining_days,
    SnmpLevelNew          AS snmp_level_new,
    lValueLast            AS level_last,
    lValueNew             AS level_new,
    ContractId            AS contract_id,
    Refilled              AS occurred_at
FROM ACCMARKERREFILL
"""


def fetch_marker_refills(limit: int | None = None) -> Iterator[dict[str, Any]]:
    """Yield consumable/CRU change events from ACCMARKERREFILL (read-only).

    Includes the cartridge serial + real pages run + OEM target — the basis for
    false-report detection, OEM-vs-real yield, and serial-backed warranty evidence.
    `occurred_at` (Refilled) is normalised to UTC.
    """
    sql = _MARKER_SQL
    if limit:
        sql = sql.replace("SELECT\n", f"SELECT TOP ({int(limit)})\n", 1)
    with fleetmgmt_engine().connect() as conn:
        for row in conn.execute(text(sql)).mappings():
            rec = dict(row)
            occ = rec.get("occurred_at")
            if occ is not None and occ.tzinfo is None:
                rec["occurred_at"] = occ.replace(tzinfo=UTC)
            yield rec


# Current per-marker predictions: Actual=1 is the latest SNMP reading per marker.
_SNMP_PRED_SQL = """
SELECT
    DeviceId             AS fleetmgmt_device_id,
    SnmpColorant         AS colorant,
    SnmpClass            AS marker_class,
    Name                 AS marker_name,
    TRY_CAST(SnmpLevel AS int) AS snmp_level,
    Slope                AS slope,
    RemainingPages       AS remaining_pages,
    RemainingDays        AS remaining_days,
    PageCount            AS page_count,
    EmptyDate            AS empty_date,
    NotificationDate     AS notification_date,
    SerialNo             AS cartridge_serial,
    CoveragePercent      AS coverage_percent,
    TimeUTC              AS reading_at
FROM ACCSNMPHISTORY WHERE Actual = 1
"""


def fetch_snmp_predictions(limit: int | None = None) -> Iterator[dict[str, Any]]:
    """Yield the current consumable/part prediction per device-marker (read-only)."""
    sql = _SNMP_PRED_SQL
    if limit:
        sql = sql.replace("SELECT\n", f"SELECT TOP ({int(limit)})\n", 1)
    with fleetmgmt_engine().connect() as conn:
        for row in conn.execute(text(sql)).mappings():
            rec = dict(row)
            occ = rec.get("reading_at")
            if occ is not None and occ.tzinfo is None:
                rec["reading_at"] = occ.replace(tzinfo=UTC)
            for k in ("empty_date", "notification_date"):
                v = rec.get(k)
                if v is not None and hasattr(v, "date"):
                    rec[k] = v.date()
            yield rec


# Printer/SNMP alert history. Non-PII: `ClearedBy`/`EventNote` (human-entered) and
# `CecData` (raw diagnostic blob) are deliberately excluded. `Raised`/`Cleared` are
# UTC. Open alert = `Cleared IS NULL`.
_EVENT_SQL = """
SELECT
    pkId             AS source_pkid,
    DeviceId         AS fleetmgmt_device_id,
    Severity         AS severity,
    AlertCode        AS alert_code,
    AlertGroup       AS alert_group,
    PrinterError     AS printer_error,
    Message          AS message,
    AlertDescription AS alert_description,
    PageCount        AS page_count_at_event,
    ContractId       AS contract_id,
    Raised           AS raised_at,
    Cleared          AS cleared_at
FROM ACCEVENTHISTORY
WHERE DeviceId IS NOT NULL
"""


def fetch_events(limit: int | None = None, since_days: int | None = None) -> Iterator[dict[str, Any]]:
    """Yield printer/SNMP alert events from ACCEVENTHISTORY (read-only).

    The basis for service-quality routes (problem models/devices, top alert codes,
    open-event aging). `since_days` bounds the window (None = full history);
    `raised_at`/`cleared_at` are normalised to UTC.
    """
    sql = _EVENT_SQL
    if since_days:
        sql += f" AND Raised >= DATEADD(day, -{int(since_days)}, SYSUTCDATETIME())"
    if limit:
        sql = sql.replace("SELECT\n", f"SELECT TOP ({int(limit)})\n", 1)
    with fleetmgmt_engine().connect() as conn:
        for row in conn.execute(text(sql)).mappings():
            rec = dict(row)
            for k in ("raised_at", "cleared_at"):
                v = rec.get(k)
                if v is not None and v.tzinfo is None:
                    rec[k] = v.replace(tzinfo=UTC)
            yield rec


def ping() -> bool:
    """Lightweight connectivity check against FleetMgmt MSSQL."""
    with fleetmgmt_engine().connect() as conn:
        return conn.execute(text("SELECT 1")).scalar() == 1
