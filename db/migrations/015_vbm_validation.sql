-- 015_vbm_validation.sql
-- Cross-check FleetMgmt-tracked consumable/part changes against Radix material.
-- A FleetMgmt "change" is corroborated when Radix shows a material line for the
-- same device within +/- 21 days. Combined with the FleetMgmt false-report flag
-- (same cartridge serial reinserted, or level jump with < 100 pages = door open/
-- close), this validates whether a part was REALLY replaced or only faked.
--   radix_bestaetigt — Radix material found near the event (real)
--   verdacht_fake    — flagged as false report AND no Radix material (likely fake)
--   nur_fleet        — FleetMgmt only, no Radix counterpart (e.g. customer-supplied
--                      toner or contract-included; not necessarily fake)
-- Limited to actual replacements + suspects (real_new_cartridge / likely_false_report).
CREATE OR REPLACE VIEW insights.vw_vbm_validation AS
WITH cand AS (
    SELECT
        v.fleetmgmt_device_id, v.colorant, v.marker_name, v.cartridge_serial,
        v.occurred_at, v.classification, v.likely_false_report, v.pages_since_previous,
        d.manufacturer_serial AS device_serial, d.customer_name,
        d.manufacturer_canonical, d.model_display
    FROM insights.vw_vbm_lifecycle v
    JOIN insights.devices_unified d ON d.fleetmgmt_device_id = v.fleetmgmt_device_id
    WHERE v.classification = 'real_new_cartridge' OR v.likely_false_report
)
SELECT
    cand.customer_name, cand.manufacturer_canonical, cand.model_display, cand.device_serial,
    cand.colorant, cand.marker_name, cand.cartridge_serial, cand.occurred_at::date AS event_date,
    cand.classification, cand.likely_false_report, cand.pages_since_previous,
    m.radix_material_found,
    CASE
        WHEN m.radix_material_found THEN 'radix_bestaetigt'
        WHEN cand.likely_false_report THEN 'verdacht_fake'
        ELSE 'nur_fleet'
    END AS validierung,
    'fleetmgmt+radix'::varchar AS source_system
FROM cand
LEFT JOIN LATERAL (
    SELECT EXISTS (
        SELECT 1 FROM insights.cost_events ce
        WHERE ce.cost_type = 'material'
          AND ce.device_serial = cand.device_serial
          AND ce.occurred_at BETWEEN cand.occurred_at - INTERVAL '21 days'
                                 AND cand.occurred_at + INTERVAL '21 days'
    ) AS radix_material_found
) m ON TRUE;
