-- 029_fix_empty_serial.sql
-- BUG FIX: many devices (esp. Konica Minolta) report the cartridge serial as an
-- empty string '' rather than NULL. The lifecycle then saw '' = '' on every event
-- and flagged ALL of them as 'reinsert_same' / likely_false_report — wiping out
-- e.g. KM's warranty claims and overcounting false reports everywhere. Empty
-- strings are NOT a serial: treat '' as NULL (-> 'no_serial') so reinsert
-- detection only fires on a genuinely repeated real serial. Columns unchanged
-- (CREATE OR REPLACE; dependents vw_warranty_assessment/_validation/_yield stay).
CREATE OR REPLACE VIEW insights.vw_vbm_lifecycle AS
WITH base AS (
    SELECT
        e.*,
        LAG(NULLIF(e.cartridge_serial, '')) OVER w AS prev_serial,
        LAG(e.level_new)                    OVER w AS prev_level
    FROM insights.vbm_lifecycle_events e
    WINDOW w AS (PARTITION BY e.fleetmgmt_device_id, e.colorant ORDER BY e.occurred_at)
)
SELECT
    b.id, b.source_pkid, b.fleetmgmt_device_id,
    NULLIF(b.cartridge_serial, '')::varchar(100) AS cartridge_serial,
    b.colorant, b.marker_name, b.page_count_at_event, b.pages_since_previous,
    b.coverage_real_pct, b.oem_target_coverage_pct, b.oem_target_pages,
    b.remaining_pages, b.remaining_days, b.snmp_level_new, b.level_last, b.level_new,
    b.occurred_at, b.prev_serial::varchar AS prev_serial,
    CASE
        WHEN NULLIF(b.cartridge_serial, '') IS NULL THEN 'no_serial'
        WHEN b.prev_serial IS NOT NULL AND NULLIF(b.cartridge_serial, '') = b.prev_serial THEN 'reinsert_same'
        ELSE 'real_new_cartridge'
    END AS classification,
    (NULLIF(b.cartridge_serial, '') IS NOT NULL
        AND (b.prev_serial IS NULL OR NULLIF(b.cartridge_serial, '') <> b.prev_serial)) AS is_real_change,
    (
        (b.prev_serial IS NOT NULL AND NULLIF(b.cartridge_serial, '') = b.prev_serial)
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
