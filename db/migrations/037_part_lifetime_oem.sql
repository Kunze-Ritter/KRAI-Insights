-- 037_part_lifetime_oem.sql
-- OEM (manufacturer) nominal part lifetimes in PAGES, materialised from KRAI
-- (krai_pm.part_lifetimes, imported from a Konica Minolta Excel). Gives spare
-- parts a proper OEM-Soll (like toner's CoveragePagesTarget) instead of the
-- 1-year heuristic. Combined with our REAL spare-part lifetime (page-accurate),
-- this is the nominal-vs-actual warranty analysis KRAI designed (vw_warranty_
-- analysis) but never had the actual-runtime data for — which we now do.
CREATE TABLE IF NOT EXISTS insights.part_lifetime_oem (
    id                     BIGSERIAL PRIMARY KEY,
    manufacturer           VARCHAR(100),
    part_category          VARCHAR(60),    -- toner|drum|fuser|transfer_belt|...
    part_number            VARCHAR(80),
    nominal_lifetime_pages INTEGER,
    color_channel          VARCHAR(8),
    model_family           VARCHAR(60),
    source                 VARCHAR(60),    -- e.g. km_excel_v1.18
    ingested_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_part_lifetime_oem_cat ON insights.part_lifetime_oem (manufacturer, part_category);

-- Real spare-part lifetime (pages) vs OEM nominal, per manufacturer x model x
-- part type. pct_vom_oem << 100 = parts dying well before their rated life
-- (premature failure / warranty leverage). KM part categories are mapped onto
-- our teiltyp; the nominal is the median rated pages for that category.
CREATE OR REPLACE VIEW insights.vw_part_oem_comparison AS
WITH oem AS (
    SELECT
        manufacturer,
        CASE part_category
            WHEN 'fuser'              THEN 'Fixiereinheit'
            WHEN 'drum'               THEN 'Trommel/Drum'
            WHEN 'image_unit_color'   THEN 'Trommel/Drum'
            WHEN 'transfer_belt'      THEN 'Transfer'
            WHEN 'transfer_roller'    THEN 'Transfer'
            WHEN 'pickup_roller'      THEN 'Walze/Roller'
            WHEN 'developing_unit_bw' THEN 'Entwickler'
            WHEN 'toner'              THEN 'Toner'
            ELSE NULL
        END AS teiltyp,
        round(percentile_cont(0.5) WITHIN GROUP (ORDER BY nominal_lifetime_pages)) AS oem_nominal_pages
    FROM insights.part_lifetime_oem
    GROUP BY manufacturer, 2
)
SELECT
    s.hersteller, s.modell, s.teiltyp, s.geraete, s.stichproben_seiten,
    s.median_standzeit_seiten AS real_median_seiten,
    o.oem_nominal_pages,
    round(100.0 * s.median_standzeit_seiten / NULLIF(o.oem_nominal_pages, 0)) AS pct_vom_oem,
    'krai+radix+fleetmgmt'::varchar AS source_system
FROM insights.vw_part_lifetime_stats s
JOIN oem o ON o.manufacturer ILIKE s.hersteller || '%' AND o.teiltyp = s.teiltyp
WHERE s.median_standzeit_seiten IS NOT NULL AND o.teiltyp IS NOT NULL
ORDER BY pct_vom_oem ASC;
