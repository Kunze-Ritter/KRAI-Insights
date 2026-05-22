-- 025_device_hostname.sql
-- Device hostname (SNMP SysName) for the overview + service. 10,724/11,950 devices
-- carry one (e.g. "KonicaSQ1082"). Like printer_ip/mac this is device infra, not PII.
ALTER TABLE insights.devices_unified ADD COLUMN IF NOT EXISTS hostname VARCHAR(128);

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
    CASE
        WHEN d.device_status IN ('silent', 'never_reported', 'deactivated', 'deleted') THEN 0.5
        ELSE 1.0
    END AS trust_score,
    d.ingested_at,
    d.updated_at,
    d.printer_ip,
    d.mac_address,
    d.hostname
FROM insights.devices_unified d;
