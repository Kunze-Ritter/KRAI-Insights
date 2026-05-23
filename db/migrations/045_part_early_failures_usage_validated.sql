-- 045_part_early_failures_usage_validated.sql
-- CRITICAL FIX (review 2026-05-23): vw_part_early_failures flagged ANY spare part
-- re-replaced within 7-365 days as a premature failure WITHOUT checking page usage —
-- the same coverage/usage-blind error that was fixed for toner in migration 043, but
-- never applied to parts. Measured impact:
--   * 92 % of the 4077 rows used the time-only heuristic (no page check).
--   * Of the 135 time-flagged rows that DID have page data, the median ran 27.936
--     pages (p90 143.728; 23 over 100k) = heavy-use NORMAL WEAR mislabelled as warranty.
--   * Repeat-counting: 4077 rows over only 720 devices (one device x part-type had 76).
--
-- New logic — a part counts as premature only if it ran < 70 % of a USAGE reference:
--   OEM-Soll (pages)   -> konfidenz 'hoch'    (manufacturer rated life; KM Excel data)
--   peer median (pages)-> konfidenz 'mittel'  (model>=5, else manufacturer>=8, else
--                                              teiltyp>=20 samples — guards high-usage wear)
--   no page data       -> konfidenz 'niedrig' (time heuristic 7-365d, unvalidated tier)
-- Page-bearing parts now always get a reference, so heavy-use normal wear no longer
-- shows up as a claim. Page-less parts keep the time heuristic but are the clearly
-- separated low-confidence tier (the headline only counts hoch+mittel — see 046).
--
-- CREATE OR REPLACE keeps the 17 existing columns in order (dependents
-- vw_developer_unit_risk + vw_lagebericht stay valid); appends referenz_seiten /
-- pct_vom_referenz / konfidenz. The `basis` column now also names the peer reference.
CREATE OR REPLACE VIEW insights.vw_part_early_failures AS
WITH mm AS (   -- model x teiltyp median page-life (fleet-wide, >=5 samples)
    SELECT manufacturer_canonical, model_display, teiltyp,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY standzeit_seiten) AS med
    FROM insights.vw_spare_part_events
    WHERE standzeit_seiten IS NOT NULL AND standzeit_tage >= 30
      AND teiltyp NOT IN ('Toner', 'unbekannt')
    GROUP BY 1, 2, 3 HAVING count(*) >= 5
),
hm AS (        -- manufacturer x teiltyp median (coarser fallback, >=8 samples)
    SELECT manufacturer_canonical, teiltyp,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY standzeit_seiten) AS med
    FROM insights.vw_spare_part_events
    WHERE standzeit_seiten IS NOT NULL AND standzeit_tage >= 30
      AND teiltyp NOT IN ('Toner', 'unbekannt')
    GROUP BY 1, 2 HAVING count(*) >= 8
),
tm AS (        -- teiltyp median (last-resort fallback, >=20 samples)
    SELECT teiltyp,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY standzeit_seiten) AS med
    FROM insights.vw_spare_part_events
    WHERE standzeit_seiten IS NOT NULL AND standzeit_tage >= 30
      AND teiltyp NOT IN ('Toner', 'unbekannt')
    GROUP BY 1 HAVING count(*) >= 20
),
cand AS (
    SELECT spe.*,
        (SELECT du.radix_device_number FROM insights.devices_unified du
           WHERE du.manufacturer_serial = spe.device_serial LIMIT 1) AS radix_device_number,
        COALESCE(mm.med, hm.med, tm.med) AS peer_med,
        CASE WHEN mm.med IS NOT NULL THEN 'Modell-Median'
             WHEN hm.med IS NOT NULL THEN 'Hersteller-Median'
             WHEN tm.med IS NOT NULL THEN 'Teiltyp-Median' END AS peer_basis
    FROM insights.vw_spare_part_events spe
    LEFT JOIN mm ON mm.manufacturer_canonical = spe.manufacturer_canonical
                AND mm.model_display = spe.model_display AND mm.teiltyp = spe.teiltyp
    LEFT JOIN hm ON hm.manufacturer_canonical = spe.manufacturer_canonical AND hm.teiltyp = spe.teiltyp
    LEFT JOIN tm ON tm.teiltyp = spe.teiltyp
    WHERE spe.teiltyp NOT IN ('Toner', 'unbekannt')
)
SELECT
    customer_name, manufacturer_canonical, model_display, device_serial,
    teiltyp, description, einbau_datum, naechster_tausch AS erneut_getauscht,
    standzeit_tage, standzeit_seiten, diagnose, invoicing_type,
    'radix+fleetmgmt'::varchar AS source_system,
    oem_nominal_seiten, pct_vom_oem,
    CASE
        WHEN oem_nominal_seiten IS NOT NULL AND standzeit_seiten IS NOT NULL THEN 'OEM-Soll (Seiten)'
        WHEN standzeit_seiten IS NOT NULL AND peer_med IS NOT NULL          THEN peer_basis || ' (Seiten)'
        ELSE 'Zeit (ohne Seiten)'
    END AS basis,
    radix_device_number,
    COALESCE(oem_nominal_seiten, round(peer_med)::int) AS referenz_seiten,
    CASE
        WHEN oem_nominal_seiten IS NOT NULL AND standzeit_seiten IS NOT NULL THEN pct_vom_oem
        WHEN standzeit_seiten IS NOT NULL AND peer_med IS NOT NULL
             THEN round(100.0 * standzeit_seiten / NULLIF(peer_med, 0))
    END AS pct_vom_referenz,
    CASE
        WHEN oem_nominal_seiten IS NOT NULL AND standzeit_seiten IS NOT NULL THEN 'hoch'
        WHEN standzeit_seiten IS NOT NULL AND peer_med IS NOT NULL           THEN 'mittel'
        ELSE 'niedrig'
    END AS konfidenz
FROM cand
WHERE
    -- Tier 1 (hoch): OEM rated pages known -> ran < 70 % of rated
    (oem_nominal_seiten IS NOT NULL AND standzeit_seiten IS NOT NULL
        AND standzeit_tage >= 7 AND pct_vom_oem < 70)
    -- Tier 2 (mittel): peer page-median known -> ran < 70 % of peers (guards heavy-use wear)
 OR (oem_nominal_seiten IS NULL AND standzeit_seiten IS NOT NULL AND peer_med IS NOT NULL
        AND standzeit_tage >= 7 AND standzeit_seiten < 0.7 * peer_med)
    -- Tier 3 (niedrig): no page data at all -> time heuristic only (unvalidated)
 OR (standzeit_seiten IS NULL AND standzeit_tage BETWEEN 7 AND 365)
ORDER BY konfidenz, pct_vom_referenz ASC NULLS LAST, standzeit_tage ASC;
