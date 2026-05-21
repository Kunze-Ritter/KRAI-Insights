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


def match_device(serial: str | None, internal_id: str | None) -> DeviceMatch:
    """Match a single device across sources.

    TODO(device_matcher): implement the 4-step strategy against loaded source
    indexes; emit ambiguous cases to a conflict/review queue.
    """
    raise NotImplementedError("device_matcher: to be implemented after the extractors land")
