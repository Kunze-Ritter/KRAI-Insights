-- 019_material_install_check.sql
-- Reconcile WHERE a Radix-shipped toner was actually installed (per FleetMgmt).
-- Radix books a toner to a device (booked_serial); FleetMgmt shows the real
-- install on some device of the same customer (same colour, near the date). By
-- pairing them we infer the actual install location and flag misbookings:
--   korrekt              — installed on the booked device (same colour, +/-30d)
--   woanders_eingebaut   — installed only on a DIFFERENT device of the customer
--                          (booked X, fitted Y -> correct the Radix record)
--   kein_einbau_gefunden — no FleetMgmt install found (in stock / not yet fitted /
--                          customer-supplied)
-- Toner only (colour parsed from the Radix description); deep parts have no
-- FleetMgmt consumption to pair against.
CREATE OR REPLACE VIEW insights.vw_material_install_check AS
WITH radix_toner AS (
    SELECT
        ce.id, ce.radix_customer_id, ce.device_serial AS booked_serial,
        ce.occurred_at::date AS lieferdatum, ce.description, ce.article_code,
        CASE
            WHEN ce.description ILIKE '%schwarz%' OR ce.description ILIKE '%black%' THEN 'black'
            WHEN ce.description ILIKE '%cyan%' THEN 'cyan'
            WHEN ce.description ILIKE '%magenta%' THEN 'magenta'
            WHEN ce.description ILIKE '%gelb%' OR ce.description ILIKE '%yellow%' THEN 'yellow'
        END AS colorant
    FROM insights.cost_events ce
    WHERE ce.cost_type = 'material' AND ce.device_serial IS NOT NULL
      AND (ce.description ILIKE '%toner%' OR ce.description ILIKE '%patrone%' OR ce.description ILIKE '%cartridge%')
)
SELECT
    rt.radix_customer_id, rt.booked_serial, rt.colorant, rt.lieferdatum, rt.description,
    s.same_device, s.elsewhere_device,
    CASE
        WHEN s.same_device THEN 'korrekt'
        WHEN s.elsewhere_device THEN 'woanders_eingebaut'
        ELSE 'kein_einbau_gefunden'
    END AS einbau_status,
    'fleetmgmt+radix'::varchar AS source_system
FROM radix_toner rt
LEFT JOIN LATERAL (
    SELECT
        EXISTS (
            SELECT 1 FROM insights.vbm_lifecycle_events v
            JOIN insights.devices_unified d ON d.fleetmgmt_device_id = v.fleetmgmt_device_id
            WHERE d.manufacturer_serial = rt.booked_serial AND v.colorant = rt.colorant
              AND v.occurred_at::date BETWEEN rt.lieferdatum - 30 AND rt.lieferdatum + 30
        ) AS same_device,
        EXISTS (
            SELECT 1 FROM insights.vbm_lifecycle_events v
            JOIN insights.devices_unified d ON d.fleetmgmt_device_id = v.fleetmgmt_device_id
            WHERE d.radix_customer_id = rt.radix_customer_id
              AND d.manufacturer_serial IS DISTINCT FROM rt.booked_serial
              AND v.colorant = rt.colorant
              AND v.occurred_at::date BETWEEN rt.lieferdatum - 30 AND rt.lieferdatum + 30
        ) AS elsewhere_device
) s ON TRUE
WHERE rt.colorant IS NOT NULL;
