-- 021_device_network.sql
-- Printer network identity for field service: when a copier must be reinstalled
-- after a defect and the customer's IT is unreachable, the technician still needs
-- the device's IP / MAC. This is the PRINTER's own management address (device
-- infrastructure), NOT a person's client IP — ACCUSERS.ClientIPAddress stays
-- excluded. FleetMgmt ACCDEVICES.IPAddress (real IP or hostname; '0.0.0.0'
-- placeholder mapped to NULL on load) + MACAddress.
ALTER TABLE insights.devices_unified ADD COLUMN IF NOT EXISTS printer_ip   VARCHAR(64);
ALTER TABLE insights.devices_unified ADD COLUMN IF NOT EXISTS mac_address  VARCHAR(40);

-- Append the two fields to the device lookup view (CREATE OR REPLACE allows
-- adding columns at the end without a drop).
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
    d.mac_address
FROM insights.devices_unified d;
