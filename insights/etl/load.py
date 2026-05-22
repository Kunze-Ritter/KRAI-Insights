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
from insights.etl import fleetmgmt_extractor, krai_pm_extractor
from insights.etl.radix import RadixAuthManager, RadixDataClient
from insights.etl.radix.models import RadixContract, RadixWorkTime

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

_UPSERT_VBM = text(
    """
    INSERT INTO insights.vbm_lifecycle_events (
        source_pkid, fleetmgmt_device_id, cartridge_serial, colorant, marker_name,
        page_count_at_event, sum_bw, sum_color, pages_since_previous, diff_bw, diff_color,
        coverage_real_pct, oem_target_coverage_pct, oem_target_pages, remaining_pages,
        remaining_days, snmp_level_new, level_last, level_new, contract_id, occurred_at
    ) VALUES (
        :source_pkid, :fleetmgmt_device_id, :cartridge_serial, :colorant, :marker_name,
        :page_count_at_event, :sum_bw, :sum_color, :pages_since_previous, :diff_bw, :diff_color,
        :coverage_real_pct, :oem_target_coverage_pct, :oem_target_pages, :remaining_pages,
        :remaining_days, :snmp_level_new, :level_last, :level_new, :contract_id, :occurred_at
    )
    ON CONFLICT (source_pkid) DO UPDATE SET
        cartridge_serial        = EXCLUDED.cartridge_serial,
        pages_since_previous    = EXCLUDED.pages_since_previous,
        coverage_real_pct       = EXCLUDED.coverage_real_pct,
        oem_target_pages        = EXCLUDED.oem_target_pages,
        oem_target_coverage_pct = EXCLUDED.oem_target_coverage_pct,
        snmp_level_new          = EXCLUDED.snmp_level_new,
        level_last              = EXCLUDED.level_last,
        level_new               = EXCLUDED.level_new,
        occurred_at             = EXCLUDED.occurred_at,
        ingested_at             = now()
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


_SEED_MODEL_CATALOG = text(
    """
    WITH best AS (
        SELECT DISTINCT ON (manufacturer_canonical, model_display)
               manufacturer_canonical, model_display, manufacturer_model_code
        FROM (
            SELECT manufacturer_canonical, model_display, manufacturer_model_code, count(*) AS c
            FROM insights.devices_unified
            WHERE model_display IS NOT NULL AND manufacturer_canonical IS NOT NULL
              AND manufacturer_model_code IS NOT NULL
            GROUP BY 1, 2, 3
        ) z
        ORDER BY manufacturer_canonical, model_display, c DESC
    ),
    allm AS (
        SELECT DISTINCT manufacturer_canonical, model_display
        FROM insights.devices_unified
        WHERE model_display IS NOT NULL AND manufacturer_canonical IS NOT NULL
    )
    INSERT INTO insights.model_catalog (manufacturer, model_number, manufacturer_model_code)
    SELECT a.manufacturer_canonical, a.model_display, b.manufacturer_model_code
    FROM allm a LEFT JOIN best b USING (manufacturer_canonical, model_display)
    ON CONFLICT (manufacturer, model_number) DO UPDATE
       SET manufacturer_model_code = COALESCE(EXCLUDED.manufacturer_model_code, model_catalog.manufacturer_model_code),
           updated_at = now()
    """
)
_SEED_ALIAS_FLEET = text(
    """
    INSERT INTO insights.model_aliases (model_id, source_system, raw_value, kind)
    SELECT id, 'fleetmgmt', model_number, 'display_name' FROM insights.model_catalog
    ON CONFLICT (source_system, kind, raw_value) DO NOTHING
    """
)
_SEED_ALIAS_RADIX = text(
    """
    INSERT INTO insights.model_aliases (model_id, source_system, raw_value, kind)
    SELECT id, 'radix', manufacturer_model_code, 'oem_code' FROM insights.model_catalog
    WHERE manufacturer_model_code IS NOT NULL
    ON CONFLICT (source_system, kind, raw_value) DO NOTHING
    """
)
_LINK_DEVICE_MODEL = text(
    """
    UPDATE insights.devices_unified d
    SET model_id = mc.id, updated_at = now()
    FROM insights.model_catalog mc
    WHERE d.manufacturer_canonical = mc.manufacturer
      AND d.model_display = mc.model_number
      AND d.model_id IS DISTINCT FROM mc.id
    """
)


def seed_model_catalog() -> dict[str, int]:
    """Build model_catalog + model_aliases from serial-joined devices; link devices.

    Canonical model = (manufacturer_canonical, model_display); the modal Radix OEM
    code (article.model) is attached for the KRAI article_code backfill list.
    """
    with insights_engine().begin() as conn:
        conn.execute(_SEED_MODEL_CATALOG)
        conn.execute(_SEED_ALIAS_FLEET)
        conn.execute(_SEED_ALIAS_RADIX)
        linked = conn.execute(_LINK_DEVICE_MODEL).rowcount
        n_models = conn.execute(text("SELECT count(*) FROM insights.model_catalog")).scalar()
        n_codes = conn.execute(
            text("SELECT count(*) FROM insights.model_catalog WHERE manufacturer_model_code IS NOT NULL")
        ).scalar()
    logger.info("model_catalog: %d models (%d with OEM code); linked %d devices", n_models, n_codes, linked)
    return {"models": n_models, "with_code": n_codes, "linked_devices": linked}


def load_vbm_lifecycle(limit: int | None = None) -> int:
    """Load FleetMgmt consumable/CRU change events into vbm_lifecycle_events."""
    total = 0
    with insights_engine().begin() as conn:
        for batch in _batched(fleetmgmt_extractor.fetch_marker_refills(limit=limit), _BATCH):
            conn.execute(_UPSERT_VBM, list(batch))
            total += len(batch)
            logger.info("upserted VBM lifecycle events (running total %d)", total)
    return total


_UPSERT_EVENT = text(
    """
    INSERT INTO insights.fleet_events (
        source_pkid, fleetmgmt_device_id, severity, alert_code, alert_group,
        printer_error, message, alert_description, page_count_at_event,
        contract_id, raised_at, cleared_at
    ) VALUES (
        :source_pkid, :fleetmgmt_device_id, :severity, :alert_code, :alert_group,
        :printer_error, :message, :alert_description, :page_count_at_event,
        :contract_id, :raised_at, :cleared_at
    )
    ON CONFLICT (source_pkid) DO UPDATE SET
        severity     = EXCLUDED.severity,
        cleared_at   = EXCLUDED.cleared_at,
        ingested_at  = now()
    """
)


def load_events(limit: int | None = None, since_days: int | None = None) -> int:
    """Load FleetMgmt printer/SNMP alert events into insights.fleet_events."""
    total = 0
    with insights_engine().begin() as conn:
        for batch in _batched(fleetmgmt_extractor.fetch_events(limit=limit, since_days=since_days), _BATCH):
            conn.execute(_UPSERT_EVENT, list(batch))
            total += len(batch)
            logger.info("upserted fleet events (running total %d)", total)
    return total


_UPSERT_ERRORCODE = text(
    """
    INSERT INTO insights.error_code_ref (
        id, error_code, manufacturer, error_description, solution_technician_text,
        severity_level, estimated_fix_time_minutes, requires_parts, page_number,
        confidence_score, product_ids
    ) VALUES (
        :id, :error_code, :manufacturer, :error_description, :solution_technician_text,
        :severity_level, :estimated_fix_time_minutes, :requires_parts, :page_number,
        :confidence_score, CAST(:product_ids AS jsonb)
    )
    ON CONFLICT (id) DO UPDATE SET
        error_code                 = EXCLUDED.error_code,
        manufacturer               = EXCLUDED.manufacturer,
        error_description          = EXCLUDED.error_description,
        solution_technician_text   = EXCLUDED.solution_technician_text,
        severity_level             = EXCLUDED.severity_level,
        estimated_fix_time_minutes = EXCLUDED.estimated_fix_time_minutes,
        requires_parts             = EXCLUDED.requires_parts,
        page_number                = EXCLUDED.page_number,
        confidence_score           = EXCLUDED.confidence_score,
        product_ids                = EXCLUDED.product_ids,
        ingested_at                = now()
    """
)


def load_error_codes(limit: int | None = None) -> int:
    """Materialise krai_intelligence error codes into insights.error_code_ref."""
    total = 0
    with insights_engine().begin() as conn:
        for batch in _batched(krai_pm_extractor.fetch_error_codes(limit=limit), _BATCH):
            conn.execute(_UPSERT_ERRORCODE, list(batch))
            total += len(batch)
    logger.info("error_code_ref load complete: %d codes", total)
    return total


_INSERT_SNMP = text(
    """
    INSERT INTO insights.snmp_predictions (
        fleetmgmt_device_id, colorant, marker_class, marker_name, snmp_level, slope,
        remaining_pages, remaining_days, page_count, empty_date, notification_date,
        cartridge_serial, coverage_percent, reading_at
    ) VALUES (
        :fleetmgmt_device_id, :colorant, :marker_class, :marker_name, :snmp_level, :slope,
        :remaining_pages, :remaining_days, :page_count, :empty_date, :notification_date,
        :cartridge_serial, :coverage_percent, :reading_at
    )
    """
)


def load_snmp_predictions() -> int:
    """Snapshot-load current SNMP predictions (ACCSNMPHISTORY Actual=1)."""
    total = 0
    with insights_engine().begin() as conn:
        conn.exec_driver_sql("TRUNCATE insights.snmp_predictions")
        for batch in _batched(fleetmgmt_extractor.fetch_snmp_predictions(), _BATCH):
            conn.execute(_INSERT_SNMP, list(batch))
            total += len(batch)
    logger.info("snmp_predictions loaded (snapshot): %d rows", total)
    return total


_UPSERT_CONTRACT = text(
    """
    INSERT INTO insights.device_contracts (
        radix_contract_id, device_id, radix_serialnumber_id, radix_customer_id,
        code, contract_type, valid_from, valid_until, is_auto_renewal, is_done
    ) VALUES (
        :radix_contract_id, :device_id, :radix_serialnumber_id, :radix_customer_id,
        :code, :contract_type, :valid_from, :valid_until, :is_auto_renewal, :is_done
    )
    ON CONFLICT (radix_contract_id, radix_serialnumber_id) DO UPDATE SET
        device_id         = EXCLUDED.device_id,
        radix_customer_id = EXCLUDED.radix_customer_id,
        code              = EXCLUDED.code,
        contract_type     = EXCLUDED.contract_type,
        valid_from        = EXCLUDED.valid_from,
        valid_until       = EXCLUDED.valid_until,
        is_auto_renewal   = EXCLUDED.is_auto_renewal,
        is_done           = EXCLUDED.is_done,
        ingested_at       = now()
    """
)
_UPDATE_DEVICE_CONTRACT_FLAGS = text(
    """
    UPDATE insights.devices_unified d SET
        contract_active = EXISTS (
            SELECT 1 FROM insights.device_contracts c
            WHERE c.device_id = d.id AND c.valid_from <= current_date AND c.valid_until >= current_date
        ),
        contract_end = (SELECT max(c.valid_until) FROM insights.device_contracts c WHERE c.device_id = d.id),
        updated_at = now()
    WHERE d.radix_serialnumber_id IS NOT NULL
    """
)


async def _pull_contracts(targets: list[tuple[str, str]]) -> list[tuple[str, str, dict[str, Any]]]:
    """Fetch contracts per device (bounded concurrency)."""
    auth = RadixAuthManager.from_settings(get_settings())
    sem = asyncio.Semaphore(15)
    rows: list[tuple[str, str, dict[str, Any]]] = []
    async with RadixDataClient(auth) as client:
        async def one(device_id: str, snid: str) -> None:
            async with sem:
                try:
                    data = await client.get_serialnumber_contracts(snid)
                except Exception as exc:  # skip a device, keep crawling
                    logger.warning("contract fetch failed for %s: %s", snid, exc)
                    return
                for contract in data:
                    rows.append((device_id, snid, contract))

        await asyncio.gather(*(one(d, s) for d, s in targets))
    return rows


def enrich_contracts_from_radix() -> dict[str, int]:
    """Crawl Radix contracts per device into device_contracts; set contract flags."""
    with insights_engine().connect() as conn:
        targets = [
            (str(r[0]), r[1])
            for r in conn.execute(
                text(
                    "SELECT id, radix_serialnumber_id FROM insights.devices_unified "
                    "WHERE radix_serialnumber_id IS NOT NULL"
                )
            ).all()
        ]
    raw = asyncio.run(_pull_contracts(targets))
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for device_id, snid, contract in raw:
        try:
            m = RadixContract.model_validate(contract)
        except Exception:
            continue
        deduped[(m.id, snid)] = {
            "radix_contract_id": m.id,
            "device_id": device_id,
            "radix_serialnumber_id": snid,
            "radix_customer_id": m.customer_id,
            "code": m.code,
            "contract_type": m.description,
            "valid_from": m.valid_from.date() if m.valid_from else None,
            "valid_until": m.valid_until.date() if m.valid_until else None,
            "is_auto_renewal": m.is_automatic_renewal,
            "is_done": m.is_done,
        }
    params = list(deduped.values())
    with insights_engine().begin() as conn:
        for batch in _batched(params, _BATCH):
            conn.execute(_UPSERT_CONTRACT, batch)
        conn.execute(_UPDATE_DEVICE_CONTRACT_FLAGS)
        active = conn.execute(text("SELECT count(*) FROM insights.devices_unified WHERE contract_active")).scalar()
    logger.info("contracts loaded: %d rows; %d devices currently under contract", len(params), active)
    return {"contracts": len(params), "active_devices": active or 0}


_UPSERT_COST = text(
    """
    INSERT INTO insights.cost_events (
        source_id, cost_type, radix_activity_id, radix_ticket_id, radix_customer_id,
        device_serial, occurred_at, description, article_code, quantity, unit_price,
        total_eur, duration_minutes, employee_id, invoicing_type, to_billed
    ) VALUES (
        :source_id, :cost_type, :radix_activity_id, :radix_ticket_id, :radix_customer_id,
        :device_serial, :occurred_at, :description, :article_code, :quantity, :unit_price,
        :total_eur, :duration_minutes, :employee_id, :invoicing_type, :to_billed
    )
    ON CONFLICT (source_id, cost_type) DO UPDATE SET
        quantity         = EXCLUDED.quantity,
        unit_price       = EXCLUDED.unit_price,
        total_eur        = EXCLUDED.total_eur,
        duration_minutes = EXCLUDED.duration_minutes,
        invoicing_type   = EXCLUDED.invoicing_type,
        to_billed        = EXCLUDED.to_billed,
        ingested_at      = now()
    """
)


async def _pull_costs(customer_limit: int | None) -> tuple[list, list]:
    """Crawl activities per customer -> spare parts + work times (bounded concurrency)."""
    auth = RadixAuthManager.from_settings(get_settings())
    sem = asyncio.Semaphore(15)
    material: list[tuple[str, dict, dict]] = []
    labor: list[tuple[str, dict, dict]] = []
    async with RadixDataClient(auth) as client:
        customers = await client.get_customers(take=10000)
        if customer_limit:
            customers = customers[:customer_limit]

        async def per_activity(customer_id: str, activity: dict) -> None:
            async with sem:
                try:
                    parts = await client.get_activity_spareparts(activity["id"])
                    times = await client.get_activity_times(activity["id"])
                except Exception:
                    return
            material.extend((customer_id, activity, p) for p in parts)
            labor.extend((customer_id, activity, t) for t in times)

        async def per_customer(customer: dict) -> None:
            async with sem:
                try:
                    acts = await client.get_activities(customer_id=customer["id"], take=200)
                except Exception:
                    return
            await asyncio.gather(*(per_activity(customer["id"], a) for a in acts))

        await asyncio.gather(*(per_customer(c) for c in customers))
    return material, labor


def crawl_costs(customer_limit: int | None = None) -> dict[str, int]:
    """Crawl Radix material + labour costs into insights.cost_events (idempotent)."""
    material, labor = asyncio.run(_pull_costs(customer_limit))
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for customer_id, activity, s in material:
        sid = s.get("id")
        if not sid:
            continue
        qty = s.get("quantity") or 0
        price = s.get("price") or 0
        rows[(sid, "material")] = {
            "source_id": sid, "cost_type": "material",
            "radix_activity_id": activity.get("id"), "radix_ticket_id": activity.get("ticketId"),
            "radix_customer_id": customer_id,
            "device_serial": s.get("serialnumberNumberManufactorParent"),
            "occurred_at": _parse_date(s.get("date")),
            "description": s.get("description"), "article_code": s.get("articleCode"),
            "quantity": qty, "unit_price": price, "total_eur": round(price * qty, 2),
            "duration_minutes": None, "employee_id": None,
            "invoicing_type": s.get("invoicingType"), "to_billed": None,
        }
    for customer_id, activity, t in labor:
        try:
            m = RadixWorkTime.model_validate(t)
        except Exception:
            continue
        if not m.id:
            continue
        rows[(m.id, "labor")] = {
            "source_id": m.id, "cost_type": "labor",
            "radix_activity_id": m.activity_id or activity.get("id"), "radix_ticket_id": m.ticket_id,
            "radix_customer_id": customer_id, "device_serial": None,
            "occurred_at": _parse_date(t.get("date")),
            "description": None, "article_code": None, "quantity": None, "unit_price": None,
            "total_eur": None, "duration_minutes": m.duration_minutes, "employee_id": m.employee_id,
            "invoicing_type": m.invoicing_type, "to_billed": m.to_billed,
        }
    params = list(rows.values())
    with insights_engine().begin() as conn:
        for batch in _batched(params, _BATCH):
            conn.execute(_UPSERT_COST, batch)
    n_mat = sum(1 for r in params if r["cost_type"] == "material")
    n_lab = len(params) - n_mat
    logger.info("cost_events loaded: %d material + %d labour", n_mat, n_lab)
    return {"material": n_mat, "labor": n_lab}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Insights ETL load")
    parser.add_argument("--radix", action="store_true", help="enrich existing devices from Radix")
    parser.add_argument("--vbm", action="store_true", help="load VBM lifecycle events (ACCMARKERREFILL)")
    parser.add_argument("--models", action="store_true", help="seed model_catalog + aliases")
    parser.add_argument("--errorcodes", action="store_true", help="materialise KRAI error codes")
    parser.add_argument("--contracts", action="store_true", help="crawl Radix contracts per device")
    parser.add_argument("--costs", action="store_true", help="crawl Radix material+labour costs")
    parser.add_argument("--cost-limit", type=int, default=None, help="limit cost crawl to N customers")
    parser.add_argument("--snmp", action="store_true", help="snapshot-load SNMP predictions")
    parser.add_argument("--events", action="store_true", help="load FleetMgmt alert events (ACCEVENTHISTORY)")
    parser.add_argument("--events-since-days", type=int, default=None,
                        help="bound event load to the last N days (default: full history)")
    parser.add_argument("--all", action="store_true", help="FleetMgmt devices + Radix + VBM + models")
    args = parser.parse_args()
    only_flags = (args.radix or args.vbm or args.models or args.errorcodes
                  or args.contracts or args.costs or args.snmp or args.events)
    if args.all or not only_flags:
        n = load_fleetmgmt_devices()
        logger.info("FleetMgmt device load complete: %d devices processed.", n)
    if args.all or args.radix:
        m = enrich_devices_from_radix()
        logger.info("Radix enrichment complete: %d devices matched.", m)
    if args.all or args.vbm:
        v = load_vbm_lifecycle()
        logger.info("VBM lifecycle load complete: %d events processed.", v)
    if args.all or args.models:
        s = seed_model_catalog()
        logger.info("Model catalog seeded: %s", s)
    if args.all or args.snmp:
        sp = load_snmp_predictions()
        logger.info("SNMP predictions loaded: %d rows.", sp)
    if args.all or args.errorcodes:
        e = load_error_codes()
        logger.info("Error-code reference loaded: %d codes.", e)
    if args.all or args.contracts:
        ctr = enrich_contracts_from_radix()
        logger.info("Contracts loaded: %s", ctr)
    if args.all or args.events:
        ev = load_events(since_days=args.events_since_days)
        logger.info("Fleet events loaded: %d events processed.", ev)
    if args.costs:
        cst = crawl_costs(customer_limit=args.cost_limit)
        logger.info("Cost events loaded: %s", cst)
