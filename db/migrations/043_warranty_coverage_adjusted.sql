-- 043_warranty_coverage_adjusted.sql
-- CRITICAL FIX (user-found): the OEM rated page life assumes ~5% coverage
-- (ISO/IEC 19752). A customer printing at higher coverage gets FEWER pages from the
-- same toner — that is NOT a premature failure. The old formula compared raw pages
-- vs rated pages and wrongly flagged high-coverage customers as warranty cases.
-- We now compare TONER delivered, coverage-adjusted:
--   effektiv_pct = pages * real_coverage / (rated_pages * rated_coverage) * 100
-- (when real coverage is present + sane; otherwise fall back to raw pages/rated).
-- A claim = delivered < 70% of the rated TONER within warranty time.
-- Real coverage is clamped to (0.5..100] — FleetMgmt CoveragePercentIs has garbage.
-- Verified example: CAP2435126E2 ran 11597 pages @ 8.54% cov = 99% of rated toner
-- -> NOT a claim (was wrongly 58% by pages).
-- CREATE OR REPLACE: pct_of_oem now carries the coverage-adjusted value (so the
-- residual € corrects automatically); raw pages-% + coverage exposed as new columns.
CREATE OR REPLACE VIEW insights.vw_warranty_assessment AS
WITH cyc AS (
    SELECT
        v.fleetmgmt_device_id, v.colorant, v.marker_name, v.cartridge_serial,
        v.occurred_at                              AS removed_at,
        LAG(v.occurred_at) OVER w                  AS installed_at,
        v.pages_since_previous                     AS pages,
        v.oem_target_pages                         AS rated,
        v.pct_of_oem                               AS pct_seiten_roh,
        v.coverage_real_pct, v.oem_target_coverage_pct,
        v.likely_false_report, v.classification,
        CASE
            WHEN v.coverage_real_pct > 0.5 AND v.coverage_real_pct <= 100
                 AND v.oem_target_coverage_pct > 0 AND v.oem_target_pages > 0
                 AND v.pages_since_previous > 0
            THEN round((v.pages_since_previous::numeric * v.coverage_real_pct)
                       / (v.oem_target_pages * v.oem_target_coverage_pct) * 100, 1)
            ELSE v.pct_of_oem
        END AS effektiv_pct,
        (v.coverage_real_pct > 0.5 AND v.coverage_real_pct <= 100
            AND v.oem_target_coverage_pct > 0) AS coverage_belegt
    FROM insights.vw_vbm_lifecycle v
    WINDOW w AS (PARTITION BY v.fleetmgmt_device_id, v.colorant, v.marker_name ORDER BY v.occurred_at)
)
SELECT
    d.customer_name, d.customer_city, d.manufacturer_canonical, d.model_display,
    d.manufacturer_serial AS device_serial, d.radix_device_number,
    c.colorant, c.marker_name, c.cartridge_serial,
    c.installed_at::date AS installed_on, c.removed_at::date AS removed_on,
    (c.removed_at::date - c.installed_at::date) AS age_days,
    c.pages, c.rated,
    c.effektiv_pct AS pct_of_oem,           -- coverage-adjusted toner yield (drives € + class)
    (c.removed_at::date - c.installed_at::date) <= 365 AS in_time_warranty,
    CASE
        WHEN c.rated IS NULL OR c.rated <= 0 OR c.pages IS NULL OR c.pages <= 0 THEN 'unknown'
        WHEN c.pages < 100 OR (c.removed_at::date - c.installed_at::date) = 0 THEN 'artifact'
        WHEN c.likely_false_report THEN 'fehlmeldung'
        WHEN (c.removed_at::date - c.installed_at::date) <= 365 AND c.effektiv_pct < 70 THEN 'claim'
        WHEN (c.removed_at::date - c.installed_at::date) >  365 AND c.effektiv_pct < 70 THEN 'negotiation'
        WHEN (c.removed_at::date - c.installed_at::date) <= 365 THEN 'wear'
        ELSE 'normal'
    END AS warranty_class,
    'fleetmgmt'::varchar AS source_system,
    c.likely_false_report,
    c.classification AS vbm_classification,
    c.pct_seiten_roh,
    round(c.coverage_real_pct::numeric, 1) AS coverage_real_pct,
    c.coverage_belegt
FROM cyc c
JOIN insights.devices_unified d ON d.fleetmgmt_device_id = c.fleetmgmt_device_id
WHERE c.installed_at IS NOT NULL;
