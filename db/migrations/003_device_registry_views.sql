-- 003_device_registry_views.sql
-- (a) Relax the serial uniqueness: serial numbers are NOT unique in raw FleetMgmt
--     (372 duplicates, 362 among active devices — reused serials, replaced units,
--     data errors). The unified table keys on fleetmgmt_device_id (always present
--     + unique); manufacturer_serial stays the cross-system MATCH key but must not
--     be uniquely constrained. Duplicate serials are routed to match_review_queue.
-- (b) First read interface: vw_device_lookup (the agent's device_lookup route).

DROP INDEX IF EXISTS insights.uq_devices_unified_serial;
CREATE INDEX IF NOT EXISTS ix_devices_unified_serial
    ON insights.devices_unified (manufacturer_serial)
    WHERE manufacturer_serial IS NOT NULL;

CREATE OR REPLACE VIEW insights.vw_device_lookup AS
SELECT
    d.id,
    d.manufacturer_serial,
    d.radix_device_number,
    d.fleetmgmt_device_id,
    d.internal_id,
    d.customer_name,
    d.customer_city,
    d.manufacturer_canonical,
    d.model_display,
    d.manufacturer_model_code,
    d.model_id,
    d.series,
    d.device_status,
    d.telemetry_stale_days,
    d.last_data_transfer_at,
    d.last_counter_at,
    d.deployed_date,
    d.warranty_supplier,
    d.contract_active,
    d.contract_end,
    d.match_type,
    d.match_confidence,
    d.source_systems,
    -- A telemetry trust hint: stale/never-reporting devices are less trustworthy
    -- for "current" questions (agent prepends a warning for these).
    CASE
        WHEN d.device_status IN ('silent', 'never_reported', 'deactivated', 'deleted') THEN 0.5
        ELSE 1.0
    END AS trust_score,
    d.ingested_at,
    d.updated_at
FROM insights.devices_unified d;
