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
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text

from insights.core.config import get_settings
from insights.core.db import insights_engine
from insights.core.logging import get_logger
from insights.core.pii import pseudonymize_contacts
from insights.etl import fleetmgmt_extractor, krai_pm_extractor, vbm_crawler_extractor
from insights.etl.radix import RadixAuthManager, RadixDataClient
from insights.etl.radix.models import RadixContract, RadixCustomer, RadixShippingAddress, RadixWorkTime

logger = get_logger(__name__)

_BATCH = 1000

_UPSERT_FLEETMGMT = text(
    """
    INSERT INTO insights.devices_unified (
        manufacturer_serial, fleetmgmt_device_id, fleetmgmt_user_id, internal_id,
        customer_name, customer_city, manufacturer_canonical, model_display,
        printer_ip, mac_address, hostname,
        deployed_date, last_data_transfer_at, device_status, telemetry_stale_days,
        unmanaged, source_systems, updated_at
    ) VALUES (
        :serial, :device_id, :user_id, :internal_id,
        :customer_name, :customer_city, :vendor, :model_display,
        :printer_ip, :mac_address, :hostname,
        :deployed_date, :last_transfer, :status, :stale_days,
        :unmanaged, ARRAY['fleetmgmt']::varchar[], now()
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
        printer_ip             = EXCLUDED.printer_ip,
        mac_address            = EXCLUDED.mac_address,
        hostname               = EXCLUDED.hostname,
        deployed_date          = EXCLUDED.deployed_date,
        last_data_transfer_at  = EXCLUDED.last_data_transfer_at,
        device_status          = EXCLUDED.device_status,
        telemetry_stale_days   = EXCLUDED.telemetry_stale_days,
        unmanaged              = EXCLUDED.unmanaged,
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
        "printer_ip": rec.get("printer_ip"),
        "mac_address": rec.get("mac_address"),
        "hostname": rec.get("hostname"),
        "deployed_date": created.date() if created else None,
        "last_transfer": rec.get("last_data_transfer_at"),
        "status": rec.get("device_status"),
        "stale_days": rec.get("telemetry_stale_days"),
        "unmanaged": bool(rec.get("unmanaged")),
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


_UPSERT_RADIX_CUSTOMER = text(
    """
    INSERT INTO insights.radix_customers (
        radix_customer_id, number, name, optional, legalform, street, zip, city,
        country, address_id, inactive
    ) VALUES (
        :radix_customer_id, :number, :name, :optional, :legalform, :street, :zip, :city,
        :country, :address_id, :inactive
    )
    ON CONFLICT (radix_customer_id) DO UPDATE SET
        number      = EXCLUDED.number,
        name        = EXCLUDED.name,
        optional    = EXCLUDED.optional,
        legalform   = EXCLUDED.legalform,
        street      = EXCLUDED.street,
        zip         = EXCLUDED.zip,
        city        = EXCLUDED.city,
        country     = EXCLUDED.country,
        address_id  = EXCLUDED.address_id,
        inactive    = EXCLUDED.inactive,
        ingested_at = now()
    """
)


async def _pull_all_customers() -> list[dict[str, Any]]:
    """Bulk-pull the Radix customer master (paginated)."""
    auth = RadixAuthManager.from_settings(get_settings())
    out: list[dict[str, Any]] = []
    skip = 0
    async with RadixDataClient(auth) as client:
        while True:
            page = await client.get_customers(take=_BATCH, skip=skip)
            if not page:
                break
            out.extend(page)
            if len(page) < _BATCH:
                break
            skip += _BATCH
    return out


def load_radix_customers() -> int:
    """Load the Radix customer master into insights.radix_customers (PII-safe).

    Each row is validated through RadixCustomer, which drops email/phone/
    salutation — only company name + location reach the cache.
    """
    raw = asyncio.run(_pull_all_customers())
    rows: list[dict[str, Any]] = []
    for c in raw:
        try:
            m = RadixCustomer.model_validate(c)
        except Exception:
            continue
        rows.append({
            "radix_customer_id": m.id, "number": m.number, "name": m.description,
            "optional": m.optional, "legalform": m.legalform, "street": m.street,
            "zip": m.zip, "city": m.town, "country": m.country,
            "address_id": m.address_id, "inactive": m.inactive,
        })
    with insights_engine().begin() as conn:
        for batch in _batched(rows, _BATCH):
            conn.execute(_UPSERT_RADIX_CUSTOMER, batch)
    logger.info("radix_customers loaded: %d", len(rows))
    return len(rows)


_UPSERT_SHIPPING = text(
    """
    INSERT INTO insights.radix_shipping_addresses (
        id, radix_customer_id, address_id, description, street, streetnumber,
        zip, city, country, is_default, inactive
    ) VALUES (
        :id, :radix_customer_id, :address_id, :description, :street, :streetnumber,
        :zip, :city, :country, :is_default, :inactive
    )
    ON CONFLICT (id) DO UPDATE SET
        radix_customer_id = EXCLUDED.radix_customer_id,
        description = EXCLUDED.description,
        street      = EXCLUDED.street,
        streetnumber = EXCLUDED.streetnumber,
        zip         = EXCLUDED.zip,
        city        = EXCLUDED.city,
        country     = EXCLUDED.country,
        is_default  = EXCLUDED.is_default,
        inactive    = EXCLUDED.inactive,
        ingested_at = now()
    """
)


async def _pull_shipping(customer_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch delivery addresses per customer (bounded concurrency)."""
    auth = RadixAuthManager.from_settings(get_settings())
    sem = asyncio.Semaphore(15)
    rows: list[dict[str, Any]] = []
    async with RadixDataClient(auth) as client:
        async def one(cid: str) -> None:
            async with sem:
                try:
                    data = await client.get_customer_shippingaddresses(cid)
                except Exception:
                    return
            rows.extend(data)

        await asyncio.gather(*(one(c) for c in customer_ids))
    return rows


def load_shipping_addresses() -> int:
    """Load Radix delivery addresses for device-bearing customers (PII-safe)."""
    with insights_engine().connect() as conn:
        customer_ids = [
            r[0] for r in conn.execute(
                text("SELECT DISTINCT radix_customer_id FROM insights.devices_unified "
                     "WHERE radix_customer_id IS NOT NULL")
            ).all()
        ]
    raw = asyncio.run(_pull_shipping(customer_ids))
    deduped: dict[str, dict[str, Any]] = {}
    for a in raw:
        try:
            m = RadixShippingAddress.model_validate(a)
        except Exception:
            continue
        deduped[m.id] = {
            "id": m.id, "radix_customer_id": m.customer_id, "address_id": m.address_id,
            "description": m.description, "street": m.street, "streetnumber": m.streetnumber,
            "zip": m.zip, "city": m.town, "country": m.country,
            "is_default": m.is_default, "inactive": m.inactive,
        }
    rows = list(deduped.values())
    with insights_engine().begin() as conn:
        for batch in _batched(rows, _BATCH):
            conn.execute(_UPSERT_SHIPPING, batch)
    logger.info("radix_shipping_addresses loaded: %d (for %d customers)", len(rows), len(customer_ids))
    return len(rows)


_INSERT_COUNTER_DAILY = text(
    """
    INSERT INTO insights.device_counter_daily (fleetmgmt_device_id, day, page_count)
    VALUES (:fleetmgmt_device_id, :day, :page_count)
    ON CONFLICT (fleetmgmt_device_id, day) DO UPDATE SET page_count = EXCLUDED.page_count
    """
)


def load_counter_daily() -> int:
    """Snapshot-load the daily page-counter timeline (truncate + reload, ~4.9M rows)."""
    total = 0
    with insights_engine().begin() as conn:
        conn.exec_driver_sql("TRUNCATE insights.device_counter_daily")
        for batch in _batched(fleetmgmt_extractor.fetch_counter_daily(), 5000):
            conn.execute(_INSERT_COUNTER_DAILY, list(batch))
            total += len(batch)
            if total % 100000 == 0:
                logger.info("loaded counter-daily rows (running total %d)", total)
    logger.info("counter-daily timeline loaded: %d rows", total)
    return total


_UPSERT_NOTE = text(
    """
    INSERT INTO insights.activity_notes (
        radix_activity_id, radix_ticket_id, radix_customer_id, activity_date,
        activity_type, state, problem_text, technik_text, verlauf_text,
        techniker_id, techniker_name, dispo_id, dispo_name, team_name
    ) VALUES (
        :radix_activity_id, :radix_ticket_id, :radix_customer_id, :activity_date,
        :activity_type, :state, :problem_text, :technik_text, :verlauf_text,
        :techniker_id, :techniker_name, :dispo_id, :dispo_name, :team_name
    )
    ON CONFLICT (radix_activity_id) DO UPDATE SET
        state          = EXCLUDED.state,
        problem_text   = EXCLUDED.problem_text,
        technik_text   = EXCLUDED.technik_text,
        verlauf_text   = EXCLUDED.verlauf_text,
        techniker_id   = EXCLUDED.techniker_id,
        techniker_name = EXCLUDED.techniker_name,
        dispo_id       = EXCLUDED.dispo_id,
        dispo_name     = EXCLUDED.dispo_name,
        team_name      = EXCLUDED.team_name,
        ingested_at    = now()
    """
)


async def _pull_ticket_notes(customer_limit: int | None) -> list[tuple[str, dict[str, Any]]]:
    """Crawl activities per customer (bounded concurrency) — one call per customer."""
    auth = RadixAuthManager.from_settings(get_settings())
    sem = asyncio.Semaphore(15)
    rows: list[tuple[str, dict[str, Any]]] = []
    async with RadixDataClient(auth) as client:
        customers = await client.get_customers(take=10000)
        if customer_limit:
            customers = customers[:customer_limit]

        async def per_customer(cust: dict[str, Any]) -> None:
            async with sem:
                try:
                    acts = await client.get_activities(customer_id=cust["id"], take=200)
                except Exception:
                    return
            rows.extend((cust["id"], a) for a in acts)

        await asyncio.gather(*(per_customer(c) for c in customers))
    return rows


_UPSERT_EMPLOYEE = text(
    "INSERT INTO insights.radix_employees (employee_id, name) VALUES (:id, :name) "
    "ON CONFLICT (employee_id) DO UPDATE SET name = EXCLUDED.name, ingested_at = now()"
)


def crawl_ticket_notes(customer_limit: int | None = None) -> int:
    """Crawl Radix activity diagnostic text into activity_notes (contacts pseudonymised).

    Also harvests the own-staff name map (employee_id -> name) from both the assigned
    technician (employeeResponsible) and the labour logger (employee) into
    radix_employees, so even fallback ids resolve to a name. Customer contacts excluded.
    """
    raw = asyncio.run(_pull_ticket_notes(customer_limit))
    deduped: dict[str, dict[str, Any]] = {}
    employees: dict[str, str] = {}
    for cid, a in raw:
        aid = a.get("id")
        if not aid:
            continue
        for id_field, name_field in (("employeeIdResponsible", "employeeResponsible"), ("employeeId", "employee")):
            eid, ename = a.get(id_field), a.get(name_field)
            if eid and ename:
                employees[str(eid)] = str(ename)
        deduped[aid] = {
            "radix_activity_id": aid,
            "radix_ticket_id": a.get("ticketId"),
            "radix_customer_id": cid,
            "activity_date": _parse_date(a.get("date")),
            "activity_type": a.get("activityType") or a.get("activityTypeType"),
            "state": a.get("stateDescription") or a.get("state"),
            "problem_text": pseudonymize_contacts(a.get("ticketDescription")),
            "technik_text": pseudonymize_contacts(a.get("technicalDescription")),
            "verlauf_text": pseudonymize_contacts(a.get("customerDescription")),
            # Techniker = der AUSFÜHRENDE (`employee`, == Arbeitszeit-Zeile), NICHT der
            # Verantwortliche/Dispo (`employeeResponsible`, oft Office). Eigene Mitarbeiter
            # — Name laut Policy erlaubt; Kunden-Kontakte bleiben ausgeschlossen.
            "techniker_id": a.get("employeeId"),
            "techniker_name": a.get("employee"),
            "dispo_id": a.get("employeeIdResponsible"),
            "dispo_name": a.get("employeeResponsible"),
            "team_name": a.get("team"),
        }
    params = list(deduped.values())
    with insights_engine().begin() as conn:
        for batch in _batched(params, _BATCH):
            conn.execute(_UPSERT_NOTE, batch)
        emp_rows = [{"id": k, "name": v} for k, v in employees.items()]
        for batch in _batched(emp_rows, _BATCH):
            conn.execute(_UPSERT_EMPLOYEE, batch)
    logger.info("activity_notes loaded: %d (contacts pseudonymised); radix_employees: %d names",
                len(params), len(employees))
    return len(params)


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


_INSERT_PART_LIFETIME = text(
    """
    INSERT INTO insights.part_lifetime_oem (
        manufacturer, part_category, part_number, nominal_lifetime_pages,
        color_channel, model_family, source
    ) VALUES (
        :manufacturer, :part_category, :part_number, :nominal_lifetime_pages,
        :color_channel, :model_family, :source
    )
    """
)


def load_part_lifetimes() -> int:
    """Materialise KRAI OEM part lifetimes (krai_pm.part_lifetimes) into insights.

    Loescht **nur** Zeilen, deren `source` mit `km_excel` beginnt - so bleiben
    Eintraege aus anderen Quellen (z. B. `vbm_crawler:*`) unberuehrt. Das
    ersetzt das alte unbedingte TRUNCATE seit Migration 047 die natuerliche
    UNIQUE-Constraint (manufacturer, part_number) traegt.
    """
    total = 0
    with insights_engine().begin() as conn:
        conn.execute(
            text("DELETE FROM insights.part_lifetime_oem WHERE source LIKE 'km_excel%'")
        )
        for batch in _batched(krai_pm_extractor.fetch_part_lifetimes(), _BATCH):
            conn.execute(_INSERT_PART_LIFETIME, list(batch))
            total += len(batch)
    logger.info("part_lifetime_oem loaded: %d OEM lifetimes", total)
    return total


# -- VBM-Crawler-Import (KRAI-Crawler-VBM Schwesterrepo) -------------------------
# Verwendet UPSERT auf (manufacturer, part_number) - sauberer als TRUNCATE und
# laesst KM-Daten in derselben Tabelle unberuehrt.

_UPSERT_VBM_LIFETIME = text(
    """
    INSERT INTO insights.part_lifetime_oem (
        manufacturer, part_category, part_number, nominal_lifetime_pages,
        color_channel, model_family, source,
        supply_color, yield_variant, iso_standard, source_url
    ) VALUES (
        :manufacturer, :part_category, :part_number, :nominal_lifetime_pages,
        :color_channel, :model_family, :source,
        :supply_color, :yield_variant, :iso_standard, :source_url
    )
    ON CONFLICT (manufacturer, part_number)
        WHERE source LIKE 'vbm_crawler:%'
    DO UPDATE SET
        part_category          = EXCLUDED.part_category,
        nominal_lifetime_pages = EXCLUDED.nominal_lifetime_pages,
        color_channel          = EXCLUDED.color_channel,
        model_family           = EXCLUDED.model_family,
        source                 = EXCLUDED.source,
        supply_color           = EXCLUDED.supply_color,
        yield_variant          = EXCLUDED.yield_variant,
        iso_standard           = EXCLUDED.iso_standard,
        source_url             = EXCLUDED.source_url,
        ingested_at            = now()
    """
)

_UPSERT_VBM_COMPAT = text(
    """
    INSERT INTO insights.part_compatibility (
        manufacturer, part_number, color_channel,
        printer_model, vendor_printer_id, printer_url, source
    ) VALUES (
        :manufacturer, :part_number, :color_channel,
        :printer_model, :vendor_printer_id, :printer_url, :source
    )
    ON CONFLICT (manufacturer, part_number, printer_model) DO UPDATE SET
        color_channel     = EXCLUDED.color_channel,
        vendor_printer_id = EXCLUDED.vendor_printer_id,
        printer_url       = EXCLUDED.printer_url,
        source            = EXCLUDED.source,
        ingested_at       = now()
    """
)


def load_vbm_crawler() -> tuple[int, int]:
    """Importiert das KRAI-Crawler-VBM Output in part_lifetime_oem + part_compatibility.

    Loescht selektiv nur eigene Quellen (`source LIKE 'vbm_crawler:%'`) und
    schreibt anschliessend per UPSERT - so sind Wiederholungen idempotent und
    parallele Quellen (KM-Excel etc.) bleiben unberuehrt.
    """
    total_lifetimes = 0
    total_compat = 0
    with insights_engine().begin() as conn:
        conn.execute(
            text(
                "DELETE FROM insights.part_lifetime_oem "
                "WHERE source LIKE 'vbm_crawler:%'"
            )
        )
        for batch in _batched(
            vbm_crawler_extractor.fetch_vbm_crawler_lifetimes(), _BATCH
        ):
            conn.execute(_UPSERT_VBM_LIFETIME, list(batch))
            total_lifetimes += len(batch)
        conn.execute(
            text(
                "DELETE FROM insights.part_compatibility "
                "WHERE source LIKE 'vbm_crawler:%'"
            )
        )
        for batch in _batched(
            vbm_crawler_extractor.fetch_vbm_crawler_compatibility(), _BATCH
        ):
            conn.execute(_UPSERT_VBM_COMPAT, list(batch))
            total_compat += len(batch)
    logger.info(
        "VBM-Crawler-Import: %d Reichweiten, %d Kompatibilitaets-Zeilen",
        total_lifetimes,
        total_compat,
    )
    return total_lifetimes, total_compat


def refresh_model_toner_oem() -> int:
    """Baut den materialisierten Modell-Toner-Soll (model_toner_oem) neu auf.

    Zwei Quellen, beide voll rebuildbar:
    - `device_supplies`: aggregiert die schwere Per-Geraet-Matching-View vw_device_supplies
      EINMALIG auf Modell x Farbe (Median/Min/Max der OEM-Toner-Reichweite) — deckt
      HP/Lexmark/Kyocera (Migration 062).
    - `self_target`: leitet den Soll je Modell x Farbe aus KMs EIGENEN, von FleetMgmt
      gemeldeten oem_target_pages ab (Median ueber Geschwister-Events) — schliesst die
      KM-Luecke, da KM keine Crawler-Kompatibilitaet hat (Migration 063). Crawler-Zeilen
      behalten Vorrang (ON CONFLICT DO NOTHING).

    vw_vbm_lifecycle faellt auf diesen Soll zurueck, wo der gespeicherte oem_target_pages
    je Event fehlt -> Garantie + Yield bewerten weit mehr Tonerwechsel. Muss nach jeder
    Aenderung an part_lifetime_oem (VBM-Crawler) bzw. devices_unified/vbm_lifecycle_events laufen.
    """
    with insights_engine().begin() as conn:
        # Crawler-abgeleitete Zeilen neu aufbauen (Selbst-Soll bleibt erhalten).
        conn.execute(text("DELETE FROM insights.model_toner_oem WHERE source = 'device_supplies'"))
        n_cr = conn.execute(
            text(
                """
                INSERT INTO insights.model_toner_oem
                    (model_display, color_channel, oem_min, oem_median, oem_max, sku_count, is_mono_model, source)
                WITH t AS (
                    SELECT model_display, color_channel, nominal_lifetime_pages
                    FROM insights.vw_device_supplies
                    WHERE part_category = 'toner' AND nominal_lifetime_pages > 0
                      AND color_channel IN ('bw', 'c', 'm', 'y')
                ),
                mono AS (
                    SELECT model_display, bool_and(color_channel = 'bw') AS is_mono
                    FROM t GROUP BY model_display
                )
                SELECT t.model_display, t.color_channel,
                       min(t.nominal_lifetime_pages)::int,
                       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY t.nominal_lifetime_pages))::int,
                       max(t.nominal_lifetime_pages)::int,
                       count(*)::int,
                       bool_or(m.is_mono),
                       'device_supplies'
                FROM t JOIN mono m USING (model_display)
                GROUP BY t.model_display, t.color_channel
                ON CONFLICT (model_display, color_channel) DO NOTHING
                """
            )
        ).rowcount
        # Selbst-Soll (KM u. a.) neu aufbauen; Crawler-Zeilen behalten Vorrang.
        conn.execute(text("DELETE FROM insights.model_toner_oem WHERE source = 'self_target'"))
        n_self = conn.execute(
            text(
                """
                INSERT INTO insights.model_toner_oem
                    (model_display, color_channel, oem_min, oem_median, oem_max, sku_count, is_mono_model, source)
                SELECT d.model_display,
                       CASE lower(btrim(ev.colorant))
                            WHEN 'black' THEN 'bw' WHEN 'cyan' THEN 'c'
                            WHEN 'magenta' THEN 'm' WHEN 'yellow' THEN 'y' END AS chan,
                       min(ev.oem_target_pages)::int,
                       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY ev.oem_target_pages))::int,
                       max(ev.oem_target_pages)::int,
                       count(*)::int,
                       NULL::boolean,
                       'self_target'
                FROM insights.vbm_lifecycle_events ev
                JOIN insights.devices_unified d ON d.fleetmgmt_device_id = ev.fleetmgmt_device_id
                WHERE ev.oem_target_pages > 0
                  AND lower(btrim(ev.colorant)) IN ('black', 'cyan', 'magenta', 'yellow')
                  AND d.model_display IS NOT NULL
                GROUP BY d.model_display, chan
                HAVING count(*) >= 5
                ON CONFLICT (model_display, color_channel) DO NOTHING
                """
            )
        ).rowcount
    n = n_cr + n_self
    logger.info("model_toner_oem neu aufgebaut: %d Zeilen (%d device_supplies + %d self_target)",
                n, n_cr, n_self)
    return n


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


def load_technician_aliases() -> int:
    """Load config/technicians.yaml (employee_id -> Kürzel/Name) into technician_aliases.

    Config-driven (no source data): maps Radix' pseudonymous employee_id to the team's
    own initials/name for the Service dashboard. Missing file = no-op (views fall back
    to employee_id). Accepts a nested `technicians:` map or a flat employee_id->Kürzel map;
    each value may be a string (Kürzel) or a {kuerzel, name} object.
    """
    path = Path(get_settings().technician_aliases_path)
    if not path.exists():
        # Keine Config = keine Aliase: Tabelle leeren (Fallback auf employee_id), nicht stale lassen.
        logger.warning("technician_aliases: %s nicht gefunden — Aliase geleert (Fallback employee_id)", path)
        with insights_engine().begin() as conn:
            conn.exec_driver_sql("TRUNCATE insights.technician_aliases")
        return 0
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    techs = data.get("technicians", data) if isinstance(data, dict) else {}
    rows: list[dict[str, Any]] = []
    for emp, val in techs.items():
        if isinstance(val, dict):
            rows.append({"e": str(emp), "k": val.get("kuerzel"), "n": val.get("name")})
        else:
            rows.append({"e": str(emp), "k": str(val) if val is not None else None, "n": None})
    with insights_engine().begin() as conn:
        conn.exec_driver_sql("TRUNCATE insights.technician_aliases")
        if rows:
            conn.execute(
                text("INSERT INTO insights.technician_aliases (employee_id, kuerzel, name) "
                     "VALUES (:e, :k, :n) ON CONFLICT (employee_id) DO UPDATE "
                     "SET kuerzel = EXCLUDED.kuerzel, name = EXCLUDED.name, ingested_at = now()"),
                rows,
            )
    logger.info("technician_aliases loaded: %d", len(rows))
    return len(rows)


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
    parser.add_argument("--partlifetimes", action="store_true", help="materialise KRAI OEM part lifetimes")
    parser.add_argument(
        "--vbm-crawler",
        dest="vbm_crawler",
        action="store_true",
        help="import KRAI-Crawler-VBM JSON output into part_lifetime_oem + part_compatibility",
    )
    parser.add_argument("--contracts", action="store_true", help="crawl Radix contracts per device")
    parser.add_argument("--costs", action="store_true", help="crawl Radix material+labour costs")
    parser.add_argument("--cost-limit", type=int, default=None, help="limit cost crawl to N customers")
    parser.add_argument("--tickets", action="store_true", help="crawl Radix activity diagnostic text (pseudonymised)")
    parser.add_argument("--ticket-limit", type=int, default=None, help="limit ticket-notes crawl to N customers")
    parser.add_argument("--snmp", action="store_true", help="snapshot-load SNMP predictions")
    parser.add_argument("--customers", action="store_true", help="load Radix customer master (PII-safe)")
    parser.add_argument("--shipping", action="store_true", help="load Radix delivery addresses per customer")
    parser.add_argument("--events", action="store_true", help="load FleetMgmt alert events (ACCEVENTHISTORY)")
    parser.add_argument("--counters", action="store_true", help="load monthly page-counter timeline")
    parser.add_argument("--events-since-days", type=int, default=None,
                        help="bound event load to the last N days (default: full history)")
    parser.add_argument("--technicians", action="store_true",
                        help="load technician aliases from config/technicians.yaml")
    parser.add_argument("--all", action="store_true", help="FleetMgmt devices + Radix + VBM + models")
    args = parser.parse_args()
    only_flags = (args.radix or args.vbm or args.models or args.errorcodes
                  or args.contracts or args.costs or args.snmp or args.events
                  or args.customers or args.shipping or args.counters or args.tickets
                  or args.partlifetimes or args.vbm_crawler or args.technicians)
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
    if args.all or args.partlifetimes:
        pl = load_part_lifetimes()
        logger.info("OEM part lifetimes loaded: %d.", pl)
    if args.all or args.vbm_crawler:
        vl, vc = load_vbm_crawler()
        logger.info(
            "VBM crawler import: %d lifetimes, %d compatibility rows.", vl, vc
        )
    # Modell-Toner-Soll nach jeder OEM-Datenaenderung neu materialisieren
    if args.all or args.vbm_crawler or args.partlifetimes:
        mt = refresh_model_toner_oem()
        logger.info("model_toner_oem refreshed: %d rows.", mt)
    if args.all or args.contracts:
        ctr = enrich_contracts_from_radix()
        logger.info("Contracts loaded: %s", ctr)
    if args.all or args.customers:
        rc = load_radix_customers()
        logger.info("Radix customers loaded: %d.", rc)
    if args.all or args.shipping:
        sh = load_shipping_addresses()
        logger.info("Radix shipping addresses loaded: %d.", sh)
    if args.all or args.events:
        ev = load_events(since_days=args.events_since_days)
        logger.info("Fleet events loaded: %d events processed.", ev)
    if args.all or args.counters:
        cm = load_counter_daily()
        logger.info("Counter-daily timeline loaded: %d rows.", cm)
    if args.costs:
        cst = crawl_costs(customer_limit=args.cost_limit)
        logger.info("Cost events loaded: %s", cst)
    if args.tickets:
        tn = crawl_ticket_notes(customer_limit=args.ticket_limit)
        logger.info("Ticket notes loaded: %d", tn)
    if args.all or args.technicians:
        ta = load_technician_aliases()
        logger.info("Technician aliases loaded: %d", ta)
