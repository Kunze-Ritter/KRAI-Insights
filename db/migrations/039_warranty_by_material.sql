-- 039_warranty_by_material.sql
-- Break the warranty claims down BY MATERIAL so the overview shows where the saving
-- comes from. Two kinds come through FleetMgmt VBM (ACCMARKERREFILL):
--   * Toner (has a colour) -> labelled "Toner Schwarz/Cyan/Magenta/Gelb"
--   * CRU parts (no colour: Waste Toner Bottle, Fuser, Transfer, Kits) -> labelled
--     by part, so a "Waste Toner Bottle" is NOT mistaken for a colourless toner.
-- Colour casing is normalised (Cyan/cyan merge). Note: waste must be matched BEFORE
-- "toner" (a "Waste Toner Bottle" contains the word toner).
CREATE OR REPLACE VIEW insights.vw_warranty_by_material AS
WITH base AS (
    SELECT
        CASE WHEN colorant IS NOT NULL AND colorant <> '' THEN 'Toner' ELSE 'Teil (kein Toner)' END AS art,
        CASE
            WHEN colorant IS NOT NULL AND colorant <> '' THEN
                CASE lower(colorant)
                    WHEN 'black' THEN 'Toner Schwarz' WHEN 'cyan' THEN 'Toner Cyan'
                    WHEN 'magenta' THEN 'Toner Magenta' WHEN 'yellow' THEN 'Toner Gelb'
                    ELSE 'Toner ' || initcap(lower(colorant))
                END
            WHEN marker_name ILIKE '%waste%' OR marker_name ILIKE '%auffang%'
                 OR marker_name ILIKE '%resttoner%' THEN 'Resttonerbehälter'
            WHEN marker_name ILIKE '%fuser%' OR marker_name ILIKE '%fixier%'
                 OR marker_name ILIKE '%heizung%' THEN 'Fixiereinheit'
            WHEN marker_name ILIKE '%transfer%' THEN 'Transfer'
            WHEN marker_name ILIKE '%drum%' OR marker_name ILIKE '%trommel%'
                 OR marker_name ILIKE '%belicht%' THEN 'Trommel/Belichtung'
            WHEN marker_name ILIKE '%roller%' OR marker_name ILIKE '%walze%'
                 OR marker_name ILIKE '%rollenkit%' THEN 'Walze/Roller'
            WHEN marker_name ILIKE '%kit%' OR marker_name ILIKE '%wartung%'
                 OR marker_name ILIKE '%maintenance%' THEN 'Wartungskit'
            ELSE 'Sonstiges Teil'
        END AS material,
        warranty_class, pct_of_oem
    FROM insights.vw_warranty_assessment
    WHERE warranty_class IN ('claim', 'negotiation')
)
SELECT
    art, material,
    count(*) FILTER (WHERE warranty_class = 'claim')                                            AS garantiefaelle,
    round(sum(GREATEST(0, 1 - LEAST(pct_of_oem, 100) / 100.0))
          FILTER (WHERE warranty_class = 'claim')::numeric, 1)                                  AS restwert_summe,
    count(*) FILTER (WHERE warranty_class = 'negotiation')                                      AS verhandlung,
    'fleetmgmt'::varchar AS source_system
FROM base
GROUP BY art, material
ORDER BY garantiefaelle DESC;
