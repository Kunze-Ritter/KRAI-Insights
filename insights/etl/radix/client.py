"""
Low-level HTTP client for the Radix RxPlusService API (Infominds), v26.12.0.

Backed by `RadixAuthManager` so long ETL crawls survive the ~1h token expiry
(on a 401 it forces one refresh and retries). GET only — sources are strictly
read-only.

Endpoint contract verified live 2026-05-22 (OpenAPI `/swagger/v1/swagger.json`):
  - `/api/serialnumber` is the device resource; `numberManufactor` == FleetMgmt
    `SerialNo`. Its `id` (GUID) drives the `/serialnumber/*` sub-calls.
  - `/api/activity` MUST be scoped (`CustomerId` or `TicketId`) and paginated
    (`Take`/`Skip`) — an unfiltered request hangs server-side.
  - Material/labour live under `/api/activity/sparepart`, `/sparepartprice`,
    `/time` (query-param style, NOT `/activity/{id}/...`).
Query parameters are PascalCase, matching the API.
"""

from __future__ import annotations

from typing import Any

import aiohttp

from insights.core.logging import get_logger
from insights.etl.radix.auth import RadixAuthManager

logger = get_logger(__name__)


class RadixDataClient:
    """HTTP client for the Radix API backed by an auto-refreshing auth manager."""

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

    @staticmethod
    def _clean(params: dict[str, Any] | None) -> dict[str, Any]:
        """Drop None values and normalise bools to lowercase strings for the API."""
        out: dict[str, Any] = {}
        for key, value in (params or {}).items():
            if value is None:
                continue
            out[key] = "true" if value is True else "false" if value is False else value
        return out

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """GET an endpoint, refreshing the token once on a 401."""
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"
        query = self._clean(params)

        for attempt in (1, 2):
            headers = await self.auth.auth_headers(force_refresh=attempt == 2)
            try:
                async with session.get(url, headers=headers, params=query) as resp:
                    if resp.status == 401 and attempt == 1:
                        logger.warning("Radix 401 on %s — forcing token refresh and retrying", endpoint)
                        continue
                    if resp.status >= 400:
                        text = await resp.text()
                        logger.error("Radix API error %s on %s: %s", resp.status, endpoint, text[:500])
                        raise ValueError(f"HTTP {resp.status}: {text[:200]}")
                    # Radix sometimes returns JSON without an application/json content-type.
                    return await resp.json(content_type=None)
            except aiohttp.ClientError as exc:
                logger.error("Network error calling Radix %s: %s", endpoint, exc)
                raise
        raise ValueError(f"Radix request to {endpoint} failed after token refresh")

    @staticmethod
    def _unwrap(response: Any) -> list[dict[str, Any]]:
        """Normalise Radix list / `{data: [...]}` responses to a plain list."""
        if isinstance(response, list):
            return response
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        if isinstance(response, dict):
            return [response]
        logger.warning("Unexpected Radix response format: %s", type(response).__name__)
        return []

    # ----------------------------------------------------------------------
    # Customers
    # ----------------------------------------------------------------------
    async def get_customers(
        self, *, take: int = 1000, skip: int = 0, number: int | None = None,
        searchtext: str | None = None, inactive: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch the customer master (paginated)."""
        params = {"Take": take, "Skip": skip, "Number": number,
                  "Searchtext": searchtext, "Inactive": inactive}
        return self._unwrap(await self.get("/api/customer", params))

    # ----------------------------------------------------------------------
    # Devices (serialnumber) — the FleetMgmt bridge
    # ----------------------------------------------------------------------
    async def get_serialnumbers(
        self, *, number: str | None = None, customer_id: str | None = None,
        article_id: str | None = None, devices_only: bool | None = None,
        search_text: str | None = None, take: int = 1000, skip: int = 0,
    ) -> list[dict[str, Any]]:
        """Search devices. `number` matches the manufacturer serial (numberManufactor)."""
        params = {"Number": number, "CustomerId": customer_id, "ArticleId": article_id,
                  "DevicesOnly": devices_only, "SearchText": search_text,
                  "Take": take, "Skip": skip}
        return self._unwrap(await self.get("/api/serialnumber", params))

    async def get_serialnumber_details(self, serialnumber_id: str) -> list[dict[str, Any]]:
        """Installed components / accessories on a device."""
        return self._unwrap(await self.get("/api/serialnumber/details", {"SerialnumberId": serialnumber_id}))

    async def get_serialnumber_counters(self, serialnumber_id: str) -> list[dict[str, Any]]:
        """Meter readings for a device."""
        return self._unwrap(await self.get("/api/serialnumber/counter", {"SerialnumberId": serialnumber_id}))

    async def get_serialnumber_contracts(
        self, serialnumber_id: str, *, only_active: bool | None = None
    ) -> list[dict[str, Any]]:
        """Contracts (with validity dates) bound to a device."""
        params = {"SerialnumberId": serialnumber_id, "OnlyActive": only_active}
        return self._unwrap(await self.get("/api/serialnumber/contracts", params))

    async def get_serialnumber_tickets(self, serialnumber_id: str) -> list[dict[str, Any]]:
        """Tickets raised for a device."""
        return self._unwrap(await self.get("/api/serialnumber/tickets", {"SerialnumberId": serialnumber_id}))

    # ----------------------------------------------------------------------
    # Activities (tickets) + cost lines
    # ----------------------------------------------------------------------
    async def get_activities(
        self, *, customer_id: str | None = None, ticket_id: str | None = None,
        employee_id: str | None = None, state: str | None = None,
        take: int = 1000, skip: int = 0,
    ) -> list[dict[str, Any]]:
        """Fetch service activities.

        MUST be scoped by `customer_id` or `ticket_id` and paginated — an
        unfiltered call hangs server-side.
        """
        if not (customer_id or ticket_id):
            raise ValueError("get_activities requires customer_id or ticket_id (unscoped call hangs)")
        params = {"CustomerId": customer_id, "TicketId": ticket_id, "EmployeeId": employee_id,
                  "State": state, "Take": take, "Skip": skip}
        return self._unwrap(await self.get("/api/activity", params))

    async def get_activity_spareparts(self, activity_id: str) -> list[dict[str, Any]]:
        """Spare parts used in an activity (material)."""
        return self._unwrap(await self.get("/api/activity/sparepart", {"ActivityId": activity_id}))

    async def get_activity_sparepartprice(
        self, *, activity_id: str | None = None, article_id: str | None = None,
        serialnumber_id: str | None = None,
    ) -> Any:
        """Material price (€) for a part/article."""
        params = {"ActivityId": activity_id, "ArticleId": article_id, "SerialnumberId": serialnumber_id}
        return await self.get("/api/activity/sparepartprice", params)

    async def get_activity_times(self, activity_id: str) -> list[dict[str, Any]]:
        """Work-time (labour) entries for an activity."""
        return self._unwrap(await self.get("/api/activity/time", {"ActivityId": activity_id}))

    # ----------------------------------------------------------------------
    # Lookups
    # ----------------------------------------------------------------------
    async def get_activity_states(self) -> list[dict[str, Any]]:
        """Available activity status codes."""
        return self._unwrap(await self.get("/api/activity/states"))

    async def get_activity_types(self) -> list[dict[str, Any]]:
        """Available activity type codes."""
        return self._unwrap(await self.get("/api/activity/activitytypes"))

    async def get_ticket_states(self) -> list[dict[str, Any]]:
        """Available ticket status codes."""
        return self._unwrap(await self.get("/api/ticket/states"))

    async def close(self) -> None:
        """Close the HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
