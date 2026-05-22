-- 006_fix_toner_yield_view.sql
-- OEM-vs-real yield must aggregate over ALL consumption cycles (pages_since_previous
-- > 0), not only serial-bearing 'real_change' events: many cartridges (e.g. HP
-- LaserJet E40040) do not report an electronic serial, so requiring is_real_change
-- dropped almost all yield data. With this filter the view reproduces the documented
-- yields (E40040 ~104 pct, KM C450i ~122 pct, HP X58045 ~232 pct of OEM).
CREATE OR REPLACE VIEW insights.vw_toner_yield_vs_oem AS
SELECT
    d.manufacturer_canonical,
    d.model_display,
    v.colorant,
    count(*)                                AS refills,
    count(DISTINCT v.fleetmgmt_device_id)   AS devices,
    round(avg(v.pages_since_previous))::int  AS avg_real_pages,
    round(avg(v.oem_target_pages))::int      AS oem_target_pages,
    round(avg(v.pct_of_oem), 1)              AS avg_pct_of_oem,
    'fleetmgmt'::varchar AS source_system
FROM insights.vw_vbm_lifecycle v
JOIN insights.devices_unified d ON d.fleetmgmt_device_id = v.fleetmgmt_device_id
WHERE v.oem_target_pages > 0 AND v.pages_since_previous > 0
GROUP BY d.manufacturer_canonical, d.model_display, v.colorant;
