-- 018_vbm_validation_customer.sql
-- Refine vw_vbm_validation with a CUSTOMER-level tier. Customers redistribute
-- material from their own stock across their fleet, so a part delivered to the
-- customer but consumed on a *different* device of the same customer is still a
-- real change — not a fake. Tiers (most → least certain):
--   radix_geraet  — Radix material for the SAME device (+/-21d)
--   radix_kunde   — Radix material for the same CUSTOMER (different device possible)
--   verdacht_fake — false-report flag AND no Radix material at all (door open/close)
--   nur_fleet     — no Radix counterpart (customer-supplied / contract-included)
-- (column set changes from migration 015, so drop + recreate.)
DROP VIEW IF EXISTS insights.vw_vbm_validation;
CREATE VIEW insights.vw_vbm_validation AS
WITH cand AS (
    SELECT
        v.fleetmgmt_device_id, v.colorant, v.marker_name, v.cartridge_serial,
        v.occurred_at, v.classification, v.likely_false_report, v.pages_since_previous,
        d.manufacturer_serial AS device_serial, d.radix_customer_id, d.customer_name,
        d.manufacturer_canonical, d.model_display
    FROM insights.vw_vbm_lifecycle v
    JOIN insights.devices_unified d ON d.fleetmgmt_device_id = v.fleetmgmt_device_id
    WHERE v.classification = 'real_new_cartridge' OR v.likely_false_report
)
SELECT
    cand.customer_name, cand.manufacturer_canonical, cand.model_display, cand.device_serial,
    cand.colorant, cand.marker_name, cand.cartridge_serial, cand.occurred_at::date AS event_date,
    cand.classification, cand.likely_false_report, cand.pages_since_previous,
    m.geraet_match, m.kunde_match,
    CASE
        WHEN m.geraet_match THEN 'radix_geraet'
        WHEN m.kunde_match THEN 'radix_kunde'
        WHEN cand.likely_false_report THEN 'verdacht_fake'
        ELSE 'nur_fleet'
    END AS validierung,
    'fleetmgmt+radix'::varchar AS source_system
FROM cand
LEFT JOIN LATERAL (
    SELECT
        EXISTS (
            SELECT 1 FROM insights.cost_events ce
            WHERE ce.cost_type = 'material' AND ce.device_serial = cand.device_serial
              AND ce.occurred_at BETWEEN cand.occurred_at - INTERVAL '21 days'
                                     AND cand.occurred_at + INTERVAL '21 days'
        ) AS geraet_match,
        EXISTS (
            SELECT 1 FROM insights.cost_events ce
            WHERE ce.cost_type = 'material'
              AND cand.radix_customer_id IS NOT NULL
              AND ce.radix_customer_id = cand.radix_customer_id
              AND ce.occurred_at BETWEEN cand.occurred_at - INTERVAL '21 days'
                                     AND cand.occurred_at + INTERVAL '21 days'
        ) AS kunde_match
) m ON TRUE;
