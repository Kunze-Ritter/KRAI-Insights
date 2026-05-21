"""
Low-level HTTP client for the Radix RxPlusService API.

Ported from KRAI (`backend/pm/services/radix_data_client.py`) with one key
change: instead of a fixed bearer token, it takes a `RadixAuthManager` and
fetches a valid token per request, so long-running ETL jobs survive the ~1h
token expiry. On a 401 it forces a refresh once and retries.

Only GET requests — no mutation allowed (sources are strictly read-only).
"""

from __future__ import annotations

from typing import Any

import aiohttp

from insights.core.logging import get_logger
from insights.etl.radix.auth import RadixAuthManager

logger = get_logger(__name__)


class RadixDataClient:
    """HTTP client for Radix API backed by an auto-refreshing auth manager."""

    def __init__(self, auth: RadixAuthManager) -> None:
        self.auth = auth
        self.base_url = auth.base_url
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> RadixDataClient:
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """GET an endpoint, refreshing the token once on a 401."""
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"

        for attempt in (1, 2):
            headers = await self.auth.auth_headers(force_refresh=attempt == 2)
            try:
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 401 and attempt == 1:
                        logger.warning("Radix 401 on %s — forcing token refresh and retrying", endpoint)
                        continue
                    if resp.status >= 400:
                        text = await resp.text()
                        logger.error("Radix API error %s on %s: %s", resp.status, endpoint, text[:500])
                        raise ValueError(f"HTTP {resp.status}: {text[:200]}")
                    return await resp.json()
            except aiohttp.ClientError as exc:
                logger.error("Network error calling Radix %s: %s", endpoint, exc)
                raise
        raise ValueError(f"Radix request to {endpoint} failed after token refresh")

    @staticmethod
    def _unwrap(response: Any) -> list[dict[str, Any]]:
        """Normalise Radix list/`{data: [...]}` responses to a plain list."""
        if isinstance(response, list):
            return response
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        logger.warning("Unexpected Radix response format: %s", type(response).__name__)
        return []

    async def get_activities(
        self, filters: dict[str, Any] | None = None, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Fetch service activities (tickets)."""
        params = dict(filters or {})
        params.setdefault("limit", limit)
        logger.info("Fetching activities with filters: %s", filters)
        return self._unwrap(await self.get("/api/activity", params))

    async def get_activity_by_id(self, activity_id: str) -> dict[str, Any]:
        """Fetch a single activity by ID."""
        logger.info("Fetching activity %s", activity_id)
        return await self.get(f"/api/activity/{activity_id}")

    async def get_activity_spare_parts(self, activity_id: str) -> list[dict[str, Any]]:
        """Fetch spare parts for an activity."""
        logger.info("Fetching spare parts for activity %s", activity_id)
        return self._unwrap(await self.get(f"/api/activity/{activity_id}/sparepart"))

    async def get_activity_work_times(self, activity_id: str) -> list[dict[str, Any]]:
        """Fetch work-time entries for an activity."""
        logger.info("Fetching work times for activity %s", activity_id)
        return self._unwrap(await self.get(f"/api/activity/{activity_id}/time"))

    async def get_activity_states(self) -> list[dict[str, Any]]:
        """Fetch available activity status codes."""
        return self._unwrap(await self.get("/api/activity/states"))

    async def get_activity_types(self) -> list[dict[str, Any]]:
        """Fetch available activity type codes."""
        return self._unwrap(await self.get("/api/activity/activitytypes"))

    async def close(self) -> None:
        """Close the HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
