"""
Device-matching engine.

Fuses FleetMgmt + Radix + KRAI-PM device records into insights.devices_unified
via the mandatory double identifier (manufacturer_serial, internal_id):

  1. Hard match  — manufacturer_serial  (FleetMgmt.SerialNo == Radix.deviceSerial)
  2. Soft match  — internal_id          (FleetMgmt.Location regex 'ID:(\\d+)')
  3. Conflict    — both identifiers point at different records -> review queue
  4. NULL-handling for the ~5.2% of devices without VendorId in FleetMgmt

Target match rate >90% (Top-50 customer mapping closes the last ~5%).

Skeleton for the `device_matcher` todo — to be implemented after the extractors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import text

from insights.core.db import insights_engine
from insights.core.logging import get_logger

logger = get_logger(__name__)

# Internal id embedded in FleetMgmt ACCDEVICES.Location, e.g. "...ID:17484...".
INTERNAL_ID_RE = re.compile(r"ID[:\s]*(\d{3,})", re.IGNORECASE)


class MatchType(StrEnum):
    """How a device record was matched across sources."""

    HARD_SERIAL = "hard_serial"
    SOFT_INTERNAL_ID = "soft_internal_id"
    MANUAL_MAPPING = "manual_mapping"
    CONFLICT = "conflict"
    UNMATCHED = "unmatched"


@dataclass(slots=True)
class DeviceMatch:
    """Result of attempting to match one device across sources."""

    manufacturer_serial: str | None
    internal_id: str | None
    match_type: MatchType
    confidence: float  # 0.0 .. 1.0
    notes: str = ""


def extract_internal_id(location: str | None) -> str | None:
    """Extract the canonical internal id from a FleetMgmt Location string."""
    if not location:
        return None
    m = INTERNAL_ID_RE.search(location)
    return m.group(1) if m else None


def run_matching() -> dict[str, int]:
    """Reconcile match state in devices_unified (set-based, idempotent).

    Serial hard-matching to Radix already happens in `load.enrich_devices_from_radix`
    (match_type='serial'). This step:
      1. marks the remainder 'unmatched' (serial present, not found in Radix);
      2. (re)populates the review queue with duplicate serials — the only
         actionable data-quality issue (most 'unmatched' are simply FleetMgmt-only
         devices, not in Radix, so they are flagged on the row, not queued).

    NOTE: an internal_id->Radix-number fallback was evaluated but yields only ~30
    extra matches (most unmatched devices are genuinely absent from Radix), so it
    is intentionally not run here.
    """
    with insights_engine().begin() as conn:
        unmatched = conn.execute(
            text(
                "UPDATE insights.devices_unified SET match_type = 'unmatched', updated_at = now() "
                "WHERE radix_device_number IS NULL AND match_type IS NULL"
            )
        ).rowcount
        conn.execute(
            text(
                "DELETE FROM insights.match_review_queue WHERE resolved = FALSE AND reason = 'duplicate_serial'"
            )
        )
        dups = conn.execute(
            text(
                """
                INSERT INTO insights.match_review_queue (manufacturer_serial, reason, details)
                SELECT manufacturer_serial, 'duplicate_serial',
                       jsonb_build_object('device_count', count(*),
                                          'fleetmgmt_device_ids', jsonb_agg(fleetmgmt_device_id))
                FROM insights.devices_unified
                WHERE manufacturer_serial IS NOT NULL
                GROUP BY manufacturer_serial
                HAVING count(*) > 1
                RETURNING 1
                """
            )
        ).rowcount
    stats = {"marked_unmatched": unmatched, "duplicate_serial_groups": dups}
    logger.info("device matching reconciled: %s", stats)
    return stats


if __name__ == "__main__":
    run_matching()
