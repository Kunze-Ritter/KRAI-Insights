-- 016_snmp_predictions.sql
-- Current consumable/part predictions per device (FleetMgmt ACCSNMPHISTORY where
-- Actual=1 = the latest reading per marker). Carries the precomputed RemainingDays
-- / EmptyDate / level per toner colour and per part (drum, transfer, cleaning unit).
-- This is the basis for predictive maintenance: "toner soon empty", "part due".
-- Snapshot table: fully replaced on each load. No PII.
CREATE TABLE IF NOT EXISTS insights.snmp_predictions (
    id                  BIGSERIAL PRIMARY KEY,
    fleetmgmt_device_id INTEGER,
    colorant            VARCHAR(20),
    marker_class        VARCHAR(20),
    marker_name         VARCHAR(200),
    snmp_level          INTEGER,        -- 0..100 fill level
    slope               DOUBLE PRECISION,
    remaining_pages     INTEGER,
    remaining_days      INTEGER,
    page_count          INTEGER,
    empty_date          DATE,
    notification_date   DATE,
    cartridge_serial    VARCHAR(100),
    coverage_percent    DOUBLE PRECISION,
    reading_at          TIMESTAMPTZ,
    source_system       VARCHAR(20) NOT NULL DEFAULT 'fleetmgmt',
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_snmp_pred_device ON insights.snmp_predictions (fleetmgmt_device_id);
CREATE INDEX IF NOT EXISTS ix_snmp_pred_remaining ON insights.snmp_predictions (remaining_days);

-- Consumables/parts due soon (live devices only; ordered by urgency).
CREATE OR REPLACE VIEW insights.vw_consumables_due AS
SELECT
    d.customer_name,
    d.customer_city,
    d.manufacturer_canonical,
    d.model_display,
    d.manufacturer_serial AS device_serial,
    d.radix_device_number,
    s.colorant,
    s.marker_name,
    s.snmp_level,
    s.remaining_days,
    s.empty_date,
    s.cartridge_serial,
    'fleetmgmt'::varchar AS source_system
FROM insights.snmp_predictions s
JOIN insights.devices_unified d ON d.fleetmgmt_device_id = s.fleetmgmt_device_id
WHERE s.remaining_days IS NOT NULL AND s.remaining_days > 0 AND d.device_status = 'live';
