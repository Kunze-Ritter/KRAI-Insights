"""
ETL load orchestrator — upserts source data into the Insights cache.

Idempotent. FleetMgmt devices are keyed on `fleetmgmt_device_id` (always present
and unique); `manufacturer_serial` is a non-unique match key. Radix enrichment
matches by serial (numberManufactor == SerialNo) and adds NON-sensitive device
fields only (Radix device id/number, OEM model code, production date, customer
ref) — no contract/price/PII data. Writes only to `insights.*`; sources stay
read-only.

    python -m insights.etl.load              # FleetMgmt device load (default)
    python -m insights.etl.load --radix      # enrich existing devices from Radix
    python -m insights.etl.load --all        # both, in order
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterable, Iterator
from datetime import datetime
from itertools import islice
from typing import Any

from sqlalchemy import text

from insights.core.config import get_settings
from insights.core.db import insights_engine
from insights.core.logging import get_logger
from insights.etl import fleetmgmt_extractor
from insights.etl.radix import RadixAuthManager, RadixDataClient

logger = get_logger(__name__)

_BATCH = 1000

_UPSERT_FLEETMGMT = text(
    """
    INSERT INTO insights.devices_unified (
        manufacturer_serial, fleetmgmt_device_id, fleetmgmt_user_id, internal_id,
        customer_name, customer_city, manufacturer_canonical, model_display,
        deployed_date, last_data_transfer_at, device_status, telemetry_stale_days,
        source_systems, updated_at
    ) VALUES (
        :serial, :device_id, :user_id, :internal_id,
        :customer_name, :customer_city, :vendor, :model_display,
        :deployed_date, :last_transfer, :status, :stale_days,
        ARRAY['fleetmgmt']::varchar[], now()
    )
    ON CONFLICT (fleetmgmt_device_id) WHERE fleetmgmt_device_id IS NOT NULL
    DO UPDATE SET
        manufacturer_serial    = EXCLUDED.manufacturer_serial,
        fleetmgmt_user_id      = EXCLUDED.fleetmgmt_user_id,
        internal_id            = EXCLUDED.internal_id,
        customer_name          = EXCLUDED.customer_name,
        customer_city          = EXCLUDED.customer_city,
        manufacturer_canonical = EXCLUDED.manufacturer_canonical,
        model_display          = EXCLUDED.model_display,
        deployed_date          = EXCLUDED.deployed_date,
        last_data_transfer_at  = EXCLUDED.last_data_transfer_at,
        device_status          = EXCLUDED.device_status,
        telemetry_stale_days   = EXCLUDED.telemetry_stale_days,
        source_systems = (
            SELECT ARRAY(
                SELECT DISTINCT e
                FROM unnest(devices_unified.source_systems || ARRAY['fleetmgmt']::varchar[]) AS e
            )
        ),
        updated_at = now()
    """
)

_UPDATE_RADIX = text(
    """
    UPDATE insights.devices_unified SET
        radix_serialnumber_id   = :radix_serialnumber_id,
        radix_device_number     = :radix_device_number,
        manufacturer_model_code = COALESCE(:manufacturer_model_code, manufacturer_model_code),
        radix_customer_id       = :radix_customer_id,
        production_date         = :production_date,
        match_type              = 'serial',
        match_confidence        = 1.0,
        source_systems = (
            SELECT ARRAY(
                SELECT DISTINCT e
                FROM unnest(source_systems || ARRAY['radix']::varchar[]) AS e
            )
        ),
        updated_at = now()
    WHERE id = :id
    """
)


def _batched(it: Iterable[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    iterator = iter(it)
    while batch := list(islice(iterator, size)):
        yield batch


def _to_param(rec: dict[str, Any]) -> dict[str, Any]:
    created = rec.get("created")
    return {
        "serial": rec.get("serial_no"),
        "device_id": rec.get("fleetmgmt_device_id"),
        "user_id": rec.get("submitter_id"),
        "internal_id": rec.get("internal_id"),
        "customer_name": rec.get("customer_name"),
        "customer_city": rec.get("customer_city"),
        "vendor": rec.get("vendor"),
        "model_display": rec.get("model_display"),
        "deployed_date": created.date() if created else None,
        "last_transfer": rec.get("last_data_transfer_at"),
        "status": rec.get("device_status"),
        "stale_days": rec.get("telemetry_stale_days"),
    }


def load_fleetmgmt_devices(limit: int | None = None) -> int:
    """Upsert FleetMgmt devices into insights.devices_unified. Returns rows processed."""
    total = 0
    with insights_engine().begin() as conn:
        for batch in _batched(fleetmgmt_extractor.fetch_devices(limit=limit), _BATCH):
            conn.execute(_UPSERT_FLEETMGMT, [_to_param(r) for r in batch])
            total += len(batch)
            logger.info("upserted FleetMgmt devices (running total %d)", total)
    return total


def _parse_date(value: Any) -> Any:
    """ISO datetime/date string -> date (UTC); pass through None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


async def _pull_radix_devices() -> dict[str, dict[str, Any]]:
    """Bulk-pull all Radix devices (DevicesOnly), index by normalised serial."""
    auth = RadixAuthManager.from_settings(get_settings())
    index: dict[str, dict[str, Any]] = {}
    dups = 0
    skip = 0
    async with RadixDataClient(auth) as client:
        while True:
            page = await client.get_serialnumbers(devices_only=True, take=_BATCH, skip=skip)
            if not page:
                break
            for r in page:
                nm = r.get("numberManufactor")
                if not nm:
                    continue
                key = nm.strip().upper()
                article = r.get("article") or {}
                if key in index:
                    dups += 1
                index[key] = {
                    "radix_serialnumber_id": r.get("id"),
                    "radix_device_number": r.get("number"),
                    "manufacturer_model_code": article.get("model"),
                    "radix_customer_id": r.get("customerId"),
                    "production_date": _parse_date(r.get("productionDate")),
                }
            if len(page) < _BATCH:
                break
            skip += _BATCH
    logger.info("pulled %d Radix devices with serial (%d duplicate serials, last wins)", len(index), dups)
    return index


def enrich_devices_from_radix() -> int:
    """Match devices_unified rows to Radix by serial; add non-sensitive Radix fields."""
    index = asyncio.run(_pull_radix_devices())
    with insights_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT id, manufacturer_serial FROM insights.devices_unified WHERE manufacturer_serial IS NOT NULL")
        ).all()
    updates: list[dict[str, Any]] = []
    for device_id, serial in rows:
        rec = index.get(serial.strip().upper())
        if rec:
            updates.append({**rec, "id": device_id})
    matched = 0
    with insights_engine().begin() as conn:
        for batch in _batched(updates, _BATCH):
            conn.execute(_UPDATE_RADIX, batch)
            matched += len(batch)
            logger.info("enriched devices from Radix (running total %d)", matched)
    logger.info("Radix enrichment complete: %d of %d serial-bearing devices matched", matched, len(rows))
    return matched


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Insights ETL load")
    parser.add_argument("--radix", action="store_true", help="enrich existing devices from Radix")
    parser.add_argument("--all", action="store_true", help="FleetMgmt load + Radix enrichment")
    args = parser.parse_args()
    if args.all or not args.radix:
        n = load_fleetmgmt_devices()
        logger.info("FleetMgmt device load complete: %d devices processed.", n)
    if args.all or args.radix:
        m = enrich_devices_from_radix()
        logger.info("Radix enrichment complete: %d devices matched.", m)
