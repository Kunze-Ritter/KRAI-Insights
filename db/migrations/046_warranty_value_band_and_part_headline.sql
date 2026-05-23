-- 046_warranty_value_band_and_part_headline.sql
-- Two credibility fixes from the review (2026-05-23):
--
-- G1 — Honest warranty € value. The headline "~74.500 € erstattbar" was
--   residual_sum (710) x ONE global toner median (105 €) from only 65 price points,
--   spread 21..247 € (p10..p90). Worse, the global median is biased HIGH: the bulk of
--   claims are Konica Minolta (median toner 55 €) and Lexmark (~18 €), while expensive
--   toners pull the global median up. Per-manufacturer weighting lowers the central
--   estimate to ~53.000 €. We now expose:
--     claim_restwert_eur       — per-manufacturer-weighted central estimate (mfr median
--                                where >=5 price samples, else global median)
--     claim_restwert_eur_low   — residual_sum x global p10  (honest lower envelope)
--     claim_restwert_eur_high  — residual_sum x global p90  (honest upper envelope)
--   The number stays a rough order of magnitude; the band makes the uncertainty visible.
--
-- P1 — Honest spare-part headline. With 045, ersatzteil_fruehausfaelle = count(*) still
--   counted every repeat row (4077 over 720 devices, mostly unvalidated time-only). The
--   headline now counts DISTINCT devices with a USAGE-validated early failure
--   (konfidenz hoch/mittel ≈ 192 devices); the time-only tier is exposed separately as
--   ersatzteil_fruehausfaelle_zeitbasiert (devices) so nothing is hidden.
--
-- DROP+CREATE (no view depends on these two; routes query them directly).

-- Per-manufacturer toner price reference (device-joined so we can attribute by maker).
CREATE OR REPLACE VIEW insights.vw_toner_price_ref AS
SELECT
    d.manufacturer_canonical AS mfr,
    count(*)                                                            AS n,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY ce.unit_price))   AS median_eur,
    'radix'::varchar AS source_system
FROM insights.cost_events ce
JOIN insights.devices_unified d ON d.manufacturer_serial = ce.device_serial
WHERE ce.cost_type = 'material' AND ce.unit_price > 0
  AND (ce.description ILIKE '%toner%' OR ce.description ILIKE '%patrone%'
       OR ce.description ILIKE '%cartridge%')
GROUP BY d.manufacturer_canonical;

DROP VIEW IF EXISTS insights.vw_lagebericht;
CREATE VIEW insights.vw_lagebericht AS
WITH gp AS (   -- global toner price percentiles (full 65-sample pool, no device join)
    SELECT percentile_cont(0.1) WITHIN GROUP (ORDER BY unit_price) AS p10,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY unit_price) AS med,
           percentile_cont(0.9) WITHIN GROUP (ORDER BY unit_price) AS p90
    FROM insights.cost_events
    WHERE cost_type = 'material' AND unit_price > 0
      AND (description ILIKE '%toner%' OR description ILIKE '%patrone%'
           OR description ILIKE '%cartridge%')
),
resid AS (     -- residual unused-life fraction per toner claim, with maker price
    SELECT GREATEST(0, 1 - LEAST(wa.pct_of_oem, 100) / 100.0) AS frac,
           COALESCE(CASE WHEN r.n >= 5 THEN r.median_eur END, gp.med) AS price_eur
    FROM insights.vw_warranty_assessment wa
    CROSS JOIN gp
    LEFT JOIN insights.vw_toner_price_ref r ON r.mfr = wa.manufacturer_canonical
    WHERE wa.warranty_class = 'claim' AND wa.colorant IS NOT NULL AND wa.colorant <> ''
)
SELECT
    (SELECT count(*) FROM insights.vw_warranty_assessment WHERE warranty_class = 'claim')        AS garantie_claims,
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim' AND cartridge_serial IS NOT NULL)                          AS garantie_claims_serial,
    (SELECT round(avg(pct_of_oem)) FROM insights.vw_warranty_assessment WHERE warranty_class = 'claim') AS claim_schnitt_pct,
    (SELECT round(sum(GREATEST(0, 1 - LEAST(pct_of_oem, 100) / 100.0))::numeric, 1)
        FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim' AND colorant IS NOT NULL AND colorant <> '')               AS claim_restwert_summe,
    (SELECT count(*) FROM insights.vw_warranty_assessment WHERE warranty_class = 'negotiation')   AS verhandlung_kandidaten,
    -- P1: usage-validated spare-part early failures, counted as DISTINCT devices
    (SELECT count(DISTINCT device_serial) FROM insights.vw_part_early_failures
        WHERE konfidenz IN ('hoch', 'mittel'))                                                    AS ersatzteil_fruehausfaelle,
    (SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY unit_price))
        FROM insights.cost_events
        WHERE cost_type = 'material' AND unit_price > 0
          AND (description ILIKE '%toner%' OR description ILIKE '%patrone%'
               OR description ILIKE '%cartridge%'))                                               AS toner_preis_median,
    (SELECT count(*) FROM insights.vw_billing_risk)                                               AS stille_unter_vertrag,
    (SELECT count(*) FROM insights.vw_customer_device_mismatch WHERE abgleich = 'abweichung')     AS kunden_abweichung,
    (SELECT count(*) FROM insights.vw_consumables_due WHERE remaining_days <= 14)                 AS verbrauch_14d,
    (SELECT count(*) FROM insights.vw_problem_devices)                                            AS problem_geraete,
    (SELECT count(*) FROM insights.devices_unified WHERE device_status = 'live')                  AS geraete_live,
    'insights'::varchar AS source_system,
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim' AND colorant IS NOT NULL AND colorant <> '')              AS garantie_claims_toner,
    -- G1: per-manufacturer-weighted central €, plus the honest p10/p90 envelope
    (SELECT round(sum(frac * price_eur)) FROM resid)                                              AS claim_restwert_eur,
    (SELECT round(sum(frac) * (SELECT p10 FROM gp)) FROM resid)                                   AS claim_restwert_eur_low,
    (SELECT round(sum(frac) * (SELECT p90 FROM gp)) FROM resid)                                   AS claim_restwert_eur_high,
    (SELECT p10 FROM gp)                                                                          AS toner_preis_p10,
    (SELECT p90 FROM gp)                                                                          AS toner_preis_p90,
    -- transparency: the unvalidated time-only tier (devices), kept separate
    (SELECT count(DISTINCT device_serial) FROM insights.vw_part_early_failures
        WHERE konfidenz = 'niedrig')                                                              AS ersatzteil_fruehausfaelle_zeitbasiert;

DROP VIEW IF EXISTS insights.vw_warranty_by_manufacturer;
CREATE VIEW insights.vw_warranty_by_manufacturer AS
WITH gm AS (
    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY unit_price) AS med
    FROM insights.cost_events
    WHERE cost_type = 'material' AND unit_price > 0
      AND (description ILIKE '%toner%' OR description ILIKE '%patrone%'
           OR description ILIKE '%cartridge%')
)
SELECT
    wa.manufacturer_canonical AS hersteller,
    count(*) FILTER (WHERE warranty_class = 'claim')                                        AS garantiefaelle,
    count(*) FILTER (WHERE warranty_class = 'claim' AND cartridge_serial IS NOT NULL)       AS serial_belegt,
    round(avg(pct_of_oem) FILTER (WHERE warranty_class = 'claim'))                          AS claim_schnitt_pct,
    round(sum(GREATEST(0, 1 - LEAST(pct_of_oem, 100) / 100.0))
          FILTER (WHERE warranty_class = 'claim')::numeric, 1)                              AS restwert_summe,
    count(*) FILTER (WHERE warranty_class = 'negotiation')                                  AS verhandlung,
    -- per-manufacturer toner price actually used (>=5 samples, else global median)
    COALESCE(CASE WHEN r.n >= 5 THEN r.median_eur END, gm.med)                              AS toner_preis_eur,
    round(sum(GREATEST(0, 1 - LEAST(pct_of_oem, 100) / 100.0)
              * COALESCE(CASE WHEN r.n >= 5 THEN r.median_eur END, gm.med))
          FILTER (WHERE warranty_class = 'claim' AND colorant IS NOT NULL AND colorant <> '')) AS erstattbar_eur,
    'fleetmgmt+radix'::varchar AS source_system
FROM insights.vw_warranty_assessment wa
CROSS JOIN gm
LEFT JOIN insights.vw_toner_price_ref r ON r.mfr = wa.manufacturer_canonical
GROUP BY wa.manufacturer_canonical, r.n, r.median_eur, gm.med
HAVING count(*) FILTER (WHERE warranty_class IN ('claim', 'negotiation')) > 0
ORDER BY erstattbar_eur DESC NULLS LAST;
