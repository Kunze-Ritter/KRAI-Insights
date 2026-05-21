"""
Radix extractor — pulls activities / spare parts / work times via RadixDataClient.

READ-ONLY: GET requests only. Uses RadixAuthManager for auto-refreshing tokens,
so long crawls survive the ~1h token lifetime. Source-ID-keyed for idempotency.

Skeleton for the `extractors` todo — to be implemented in Phase 1 after bootstrap.
The validated Pydantic models (RadixActivity/SparePart/WorkTime) feed
insights.cost_events (Phase 4) and cross-check the FleetMgmt sensor data.
"""

from __future__ import annotations

from typing import Any

from insights.core.config import get_settings
from insights.core.logging import get_logger
from insights.etl.radix import RadixAuthManager, RadixDataClient
from insights.etl.radix.models import RadixActivity

logger = get_logger(__name__)


async def fetch_activities(
    filters: dict[str, Any] | None = None, limit: int = 1000
) -> list[RadixActivity]:
    """Fetch and validate Radix activities (read-only).

    TODO(extractors): paginate beyond `limit`, persist to insights.cost_events,
    and key on Radix activity id for idempotent re-runs.
    """
    auth = RadixAuthManager.from_settings(get_settings())
    async with RadixDataClient(auth) as client:
        raw = await client.get_activities(filters=filters, limit=limit)
    activities: list[RadixActivity] = []
    for item in raw:
        try:
            activities.append(RadixActivity.model_validate(item))
        except Exception as exc:
            logger.warning("Skipping unparseable Radix activity %s: %s", item.get("id"), exc)
    logger.info("Fetched %d Radix activities", len(activities))
    return activities


async def ping() -> bool:
    """Verify Radix auth + connectivity by requesting activity states."""
    auth = RadixAuthManager.from_settings(get_settings())
    async with RadixDataClient(auth) as client:
        await client.get_activity_states()
    return True
