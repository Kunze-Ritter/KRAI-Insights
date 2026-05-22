-- 004_vbm_lifecycle.sql
-- VBM (consumable/CRU) lifecycle events from FleetMgmt ACCMARKERREFILL — the
-- serial-backed toner/part-change history. Carries the cartridge serial (unique
-- evidence NOT in Radix), real pages run, real coverage, and the OEM target —
-- the basis for false-report detection, OEM-vs-real yield, and warranty evidence.
--
-- Classification (real_new_cartridge / reinsert_same / no_serial), pct_of_oem and
-- lifespan_rating are computed on the fly in vw_vbm_lifecycle (window over the
-- per-device/colorant history), so the base table stays a raw, rebuildable load.
-- All timestamps UTC. No PII.

CREATE TABLE IF NOT EXISTS insights.vbm_lifecycle_events (
    id                      BIGSERIAL PRIMARY KEY,
    source_pkid             BIGINT NOT NULL,            -- ACCMARKERREFILL.pkId (idempotent key)
    fleetmgmt_device_id     INTEGER,                    -- ACCMARKERREFILL.DeviceId
    cartridge_serial        VARCHAR(100),               -- ACCMARKERREFILL.SerialNo (evidence; ~31 pct filled)
    colorant                VARCHAR(20),
    marker_name             VARCHAR(200),
    page_count_at_event     BIGINT,                     -- PageCount (counter at change)
    sum_bw                  BIGINT,                     -- lSumBW
    sum_color               BIGINT,                     -- lSumColor
    pages_since_previous    INTEGER,                    -- lDiffPageCount (life of the removed cartridge)
    diff_bw                 INTEGER,                    -- lDiffSumBW
    diff_color              INTEGER,                    -- lDiffSumColor
    coverage_real_pct       NUMERIC(6, 2),              -- CoveragePercentIs
    oem_target_coverage_pct NUMERIC(6, 2),              -- CoveragePercentTarget
    oem_target_pages        INTEGER,                    -- CoveragePagesTarget (rated yield)
    remaining_pages         INTEGER,
    remaining_days          INTEGER,
    snmp_level_new          INTEGER,                    -- SnmpLevelNew
    level_last              INTEGER,                    -- lValueLast
    level_new               INTEGER,                    -- lValueNew
    contract_id             INTEGER,
    occurred_at             TIMESTAMPTZ,                -- Refilled (UTC)
    source_system           VARCHAR(20) NOT NULL DEFAULT 'fleetmgmt',
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_pkid)
);
CREATE INDEX IF NOT EXISTS ix_vbm_device ON insights.vbm_lifecycle_events (fleetmgmt_device_id);
CREATE INDEX IF NOT EXISTS ix_vbm_serial ON insights.vbm_lifecycle_events (cartridge_serial) WHERE cartridge_serial IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_vbm_device_color_time ON insights.vbm_lifecycle_events (fleetmgmt_device_id, colorant, occurred_at);

-- Classified lifecycle view: real change vs reinsert (false report), yield vs OEM.
CREATE OR REPLACE VIEW insights.vw_vbm_lifecycle AS
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

-- OEM-vs-real toner yield per model x colorant (real replacements only).
CREATE OR REPLACE VIEW insights.vw_toner_yield_vs_oem AS
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
