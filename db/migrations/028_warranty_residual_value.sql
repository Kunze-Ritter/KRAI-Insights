-- 028_warranty_residual_value.sql
-- Realistic claim value: you don't get the full cartridge price back, only the
-- UNUSED life. If a cartridge reached 32% of its rated life, 68% is reclaimable.
--   residual_fraction = 1 - (pages / rated)   (clamped to [0,1])
--   estimated € = SUM(residual_fraction over claims) x median toner price
-- We expose the residual-fraction SUM per scope so consumers multiply by the
-- (still rough) median price. (drop + recreate to add columns; no dependents.)
DROP VIEW IF EXISTS insights.vw_lagebericht;
CREATE VIEW insights.vw_lagebericht AS
SELECT
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim' AND cartridge_serial IS NOT NULL)        AS garantie_claims,
    (SELECT round(avg(pct_of_oem)) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim')                                          AS claim_schnitt_pct,
    -- sum of unused-life fractions over serial-backed claims (the realistic basis)
    (SELECT round(sum(GREATEST(0, 1 - LEAST(pct_of_oem, 100) / 100.0))::numeric, 1)
        FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim' AND cartridge_serial IS NOT NULL)         AS claim_restwert_summe,
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'negotiation' AND cartridge_serial IS NOT NULL)   AS verhandlung_kandidaten,
    (SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY unit_price))
        FROM insights.cost_events
        WHERE cost_type = 'material' AND unit_price > 0
          AND (description ILIKE '%toner%' OR description ILIKE '%patrone%'
               OR description ILIKE '%cartridge%'))                              AS toner_preis_median,
    (SELECT count(*) FROM insights.vw_billing_risk)                              AS stille_unter_vertrag,
    (SELECT count(*) FROM insights.vw_customer_device_mismatch
        WHERE abgleich = 'abweichung')                                          AS kunden_abweichung,
    (SELECT count(*) FROM insights.vw_consumables_due WHERE remaining_days <= 14) AS verbrauch_14d,
    (SELECT count(*) FROM insights.vw_problem_devices)                          AS problem_geraete,
    (SELECT count(*) FROM insights.devices_unified WHERE device_status = 'live') AS geraete_live,
    'insights'::varchar AS source_system;

DROP VIEW IF EXISTS insights.vw_warranty_by_manufacturer;
CREATE VIEW insights.vw_warranty_by_manufacturer AS
SELECT
    manufacturer_canonical AS hersteller,
    count(*) FILTER (WHERE warranty_class = 'claim' AND cartridge_serial IS NOT NULL)       AS garantiefaelle,
    round(avg(pct_of_oem) FILTER (WHERE warranty_class = 'claim'))                          AS claim_schnitt_pct,
    round(sum(GREATEST(0, 1 - LEAST(pct_of_oem, 100) / 100.0))
          FILTER (WHERE warranty_class = 'claim' AND cartridge_serial IS NOT NULL)::numeric, 1) AS restwert_summe,
    count(*) FILTER (WHERE warranty_class = 'negotiation' AND cartridge_serial IS NOT NULL) AS verhandlung,
    'fleetmgmt'::varchar AS source_system
FROM insights.vw_warranty_assessment
GROUP BY manufacturer_canonical
HAVING count(*) FILTER (WHERE warranty_class IN ('claim', 'negotiation')) > 0
ORDER BY restwert_summe DESC NULLS LAST;
