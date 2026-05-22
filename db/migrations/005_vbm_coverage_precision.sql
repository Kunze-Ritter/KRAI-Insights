-- 005_vbm_coverage_precision.sql
-- ACCMARKERREFILL.CoveragePercentIs carries out-of-range noise (max ~59,569.6;
-- a real coverage percent is <= 100) that overflows NUMERIC(6,2). Widen the
-- coverage columns to ingest the raw value; analysis/views filter implausible
-- coverage (> 100) rather than dropping rows at load.
-- The views depend on these columns, so drop + recreate them around the ALTER.

DROP VIEW IF EXISTS insights.vw_toner_yield_vs_oem;
DROP VIEW IF EXISTS insights.vw_vbm_lifecycle;

ALTER TABLE insights.vbm_lifecycle_events ALTER COLUMN coverage_real_pct TYPE NUMERIC(10, 2);
ALTER TABLE insights.vbm_lifecycle_events ALTER COLUMN oem_target_coverage_pct TYPE NUMERIC(10, 2);

CREATE VIEW insights.vw_vbm_lifecycle AS
WITH base AS (
    SELECT
        e.*,
        LAG(e.cartridge_serial) OVER w AS prev_serial,
        LAG(e.level_new)        OVER w AS prev_level
    FROM insights.vbm_lifecycle_events e
    WINDOW w AS (PARTITION BY e.fleetmgmt_device_id, e.colorant ORDER BY e.occurred_at)
)
SELECT
    b.id, b.source_pkid, b.fleetmgmt_device_id, b.cartridge_serial, b.colorant,
    b.marker_name, b.page_count_at_event, b.pages_since_previous,
    b.coverage_real_pct, b.oem_target_coverage_pct, b.oem_target_pages,
    b.remaining_pages, b.remaining_days, b.snmp_level_new, b.level_last, b.level_new,
    b.occurred_at, b.prev_serial,
    CASE
        WHEN b.cartridge_serial IS NULL THEN 'no_serial'
        WHEN b.prev_serial IS NOT NULL AND b.cartridge_serial = b.prev_serial THEN 'reinsert_same'
        ELSE 'real_new_cartridge'
    END AS classification,
    (b.cartridge_serial IS NOT NULL AND (b.prev_serial IS NULL OR b.cartridge_serial <> b.prev_serial)) AS is_real_change,
    (
        (b.prev_serial IS NOT NULL AND b.cartridge_serial = b.prev_serial)
        OR (b.pages_since_previous IS NOT NULL AND b.pages_since_previous < 100
            AND b.level_new > COALESCE(b.level_last, b.level_new))
    ) AS likely_false_report,
    CASE WHEN b.oem_target_pages > 0 AND b.pages_since_previous > 0
         THEN ROUND(b.pages_since_previous::numeric / b.oem_target_pages * 100, 1) END AS pct_of_oem,
    CASE WHEN b.oem_target_pages > 0 AND b.pages_since_previous > 0 THEN
        CASE
            WHEN b.pages_since_previous::numeric / b.oem_target_pages < 0.7  THEN 'too_few'
            WHEN b.pages_since_previous::numeric / b.oem_target_pages <= 1.3 THEN 'on_target'
            WHEN b.pages_since_previous::numeric / b.oem_target_pages <= 2.0 THEN 'top_performer'
            ELSE 'outlier'
        END
    END AS lifespan_rating,
    'fleetmgmt'::varchar AS source_system
FROM base b;

CREATE VIEW insights.vw_toner_yield_vs_oem AS
SELECT
    d.manufacturer_canonical,
    d.model_display,
    v.colorant,
    count(*)                                   AS refills,
    count(DISTINCT v.fleetmgmt_device_id)      AS devices,
    round(avg(v.pages_since_previous))::int    AS avg_real_pages,
    round(avg(v.oem_target_pages))::int        AS oem_target_pages,
    round(avg(v.pct_of_oem), 1)                AS avg_pct_of_oem,
    'fleetmgmt'::varchar AS source_system
FROM insights.vw_vbm_lifecycle v
JOIN insights.devices_unified d ON d.fleetmgmt_device_id = v.fleetmgmt_device_id
WHERE v.is_real_change AND v.oem_target_pages > 0 AND v.pages_since_previous > 0
GROUP BY d.manufacturer_canonical, d.model_display, v.colorant;
