-- 017_billing_reconciliation.sql
-- (a) Billing risk: devices under contract that no longer report → counters are
--     estimated, not real → billing/accounting risk.
-- (b) Fleet reconciliation: one row per device with the combined truth (telemetry
--     status + contract + presence in Radix) for data cleanup + outreach.
CREATE OR REPLACE VIEW insights.vw_billing_risk AS
SELECT
    customer_name, customer_city, manufacturer_serial AS device_serial, radix_device_number,
    manufacturer_canonical, model_display, device_status, telemetry_stale_days, contract_end,
    'fleetmgmt+radix'::varchar AS source_system
FROM insights.devices_unified
WHERE COALESCE(contract_active, FALSE) = TRUE
  AND device_status IN ('silent', 'never_reported');

CREATE OR REPLACE VIEW insights.vw_fleet_reconciliation AS
SELECT
    customer_name, customer_city, manufacturer_serial AS device_serial, radix_device_number,
    manufacturer_canonical, model_display, device_status, telemetry_stale_days,
    contract_active, contract_end, (radix_device_number IS NOT NULL) AS in_radix, match_type,
    CASE
        WHEN device_status = 'live' AND COALESCE(contract_active, FALSE) THEN 'aktiv_unter_vertrag'
        WHEN device_status = 'live' THEN 'aktiv_ohne_vertrag'
        WHEN device_status IN ('silent', 'never_reported') AND COALESCE(contract_active, FALSE) THEN 'still_unter_vertrag'
        WHEN device_status IN ('silent', 'never_reported') THEN 'still_ohne_vertrag'
        ELSE 'inaktiv'
    END AS einordnung,
    'fleetmgmt+radix'::varchar AS source_system
FROM insights.devices_unified;
