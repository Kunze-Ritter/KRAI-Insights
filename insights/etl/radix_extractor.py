"""
Radix extractor — pulls devices / activities / costs via RadixDataClient.

READ-ONLY: GET requests only. Uses RadixAuthManager for auto-refreshing tokens,
so long crawls survive the ~1h token lifetime. Source-ID-keyed for idempotency.

Aligned to the live API contract (see insights/etl/radix/client.py):
  - resolve a FleetMgmt serial to a Radix device via `/serialnumber`
    (numberManufactor == SerialNo);
  - activities are crawled per customer (or per ticket), paginated.
The validated Pydantic models drop PII on validation. Full crawl/persist logic
lands in Phase 1/3 (devices_unified / cost_events).
"""

from __future__ import annotations

from insights.core.config import get_settings
from insights.core.logging import get_logger
from insights.etl.radix import RadixAuthManager, RadixDataClient
from insights.etl.radix.models import RadixActivity, RadixSerialNumber

logger = get_logger(__name__)


async def resolve_device(serial: str) -> RadixSerialNumber | None:
    """Resolve a manufacturer serial to a Radix device (read-only).

    Hard bridge to FleetMgmt: `RadixSerialNumber.number_manufactor == SerialNo`.
    Returns the first exact match, or None.
    """
    auth = RadixAuthManager.from_settings(get_settings())
    async with RadixDataClient(auth) as client:
        raw = await client.get_serialnumbers(number=serial, take=5)
    for item in raw:
        try:
            sn = RadixSerialNumber.model_validate(item)
        except Exception as exc:
            logger.warning("Skipping unparseable Radix serialnumber: %s", exc)
            continue
        if sn.number_manufactor and sn.number_manufactor.strip().upper() == serial.strip().upper():
            return sn
    return None


async def fetch_activities_for_customer(
    customer_id: str, *, take: int = 1000, skip: int = 0
) -> list[RadixActivity]:
    """Fetch and validate a customer's service activities (read-only, paginated)."""
    auth = RadixAuthManager.from_settings(get_settings())
    async with RadixDataClient(auth) as client:
        raw = await client.get_activities(customer_id=customer_id, take=take, skip=skip)
    activities: list[RadixActivity] = []
    for item in raw:
        try:
            activities.append(RadixActivity.model_validate(item))
        except Exception as exc:
            logger.warning("Skipping unparseable Radix activity %s: %s", item.get("id"), exc)
    logger.info("Fetched %d Radix activities for customer %s", len(activities), customer_id)
    return activities


async def ping() -> bool:
    """Verify Radix auth + connectivity by requesting activity states."""
    auth = RadixAuthManager.from_settings(get_settings())
    async with RadixDataClient(auth) as client:
        await client.get_activity_states()
    return True
