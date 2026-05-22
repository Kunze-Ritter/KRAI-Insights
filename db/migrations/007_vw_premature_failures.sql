-- 007_vw_premature_failures.sql
-- Warranty / negotiation candidates: consumption cycles that ended well under the
-- OEM rated yield (lifespan_rating 'too_few', i.e. < 70 pct of OEM). Carries the
-- cartridge serial + real pages + OEM target + device/customer — the serial-backed
-- evidence base for manufacturer submissions (data Radix/the OEM does not have).
CREATE OR REPLACE VIEW insights.vw_premature_failures AS
SELECT
    d.customer_name,
    d.customer_city,
    d.manufacturer_canonical,
    d.model_display,
    d.manufacturer_serial   AS device_serial,
    d.radix_device_number,
    v.colorant,
    v.marker_name,
    v.cartridge_serial,
    v.pages_since_previous  AS real_pages,
    v.oem_target_pages,
    v.pct_of_oem,
    v.occurred_at::date     AS replaced_on,
    'fleetmgmt'::varchar AS source_system
FROM insights.vw_vbm_lifecycle v
JOIN insights.devices_unified d ON d.fleetmgmt_device_id = v.fleetmgmt_device_id
WHERE v.lifespan_rating = 'too_few' AND v.pages_since_previous > 0;
