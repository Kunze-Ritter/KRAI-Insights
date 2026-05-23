-- 041_warranty_age0_artifact.sql
-- Credibility: a cycle with age_days = 0 (install and removal on the SAME day) is
-- not a real cartridge life — it comes from multiple refill events logged on one
-- day (simultaneous multi-colour reporting / re-detection). Exclude such cycles
-- from claim/negotiation (-> 'artifact'), alongside the <100-page filter.
-- CREATE OR REPLACE: column set unchanged, only the classification expression.
CREATE OR REPLACE VIEW insights.vw_warranty_assessment AS
WITH cyc AS (
    SELECT
        v.fleetmgmt_device_id, v.colorant, v.marker_name, v.cartridge_serial,
        v.occurred_at                              AS removed_at,
        LAG(v.occurred_at) OVER w                  AS installed_at,
        v.pages_since_previous                     AS pages,
        v.oem_target_pages                         AS rated,
        v.pct_of_oem, v.likely_false_report, v.classification
    FROM insights.vw_vbm_lifecycle v
    WINDOW w AS (PARTITION BY v.fleetmgmt_device_id, v.colorant, v.marker_name ORDER BY v.occurred_at)
)
SELECT
    d.customer_name, d.customer_city, d.manufacturer_canonical, d.model_display,
    d.manufacturer_serial AS device_serial, d.radix_device_number,
    c.colorant, c.marker_name, c.cartridge_serial,
    c.installed_at::date AS installed_on, c.removed_at::date AS removed_on,
    (c.removed_at::date - c.installed_at::date) AS age_days,
    c.pages, c.rated, c.pct_of_oem,
    (c.removed_at::date - c.installed_at::date) <= 365 AS in_time_warranty,
    CASE
        WHEN c.rated IS NULL OR c.rated <= 0 OR c.pages IS NULL OR c.pages <= 0 THEN 'unknown'
        WHEN c.pages < 100 OR (c.removed_at::date - c.installed_at::date) = 0 THEN 'artifact'
        WHEN c.likely_false_report THEN 'fehlmeldung'
        WHEN (c.removed_at::date - c.installed_at::date) <= 365 AND c.pages < c.rated * 0.7 THEN 'claim'
        WHEN (c.removed_at::date - c.installed_at::date) <= 365 AND c.pages >= c.rated      THEN 'wear'
        WHEN (c.removed_at::date - c.installed_at::date) >  365 AND c.pages < c.rated * 0.7 THEN 'negotiation'
        ELSE 'normal'
    END AS warranty_class,
    'fleetmgmt'::varchar AS source_system,
    c.likely_false_report,
    c.classification AS vbm_classification
FROM cyc c
JOIN insights.devices_unified d ON d.fleetmgmt_device_id = c.fleetmgmt_device_id
WHERE c.installed_at IS NOT NULL;
