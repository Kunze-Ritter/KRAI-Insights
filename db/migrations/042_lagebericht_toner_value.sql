-- 042_lagebericht_toner_value.sql
-- Harden the €-estimate: the residual value uses the median TONER price, so it is
-- only meaningful for toner claims. Restrict claim_restwert_summe to claims WITH a
-- colour (= toner); CRU parts (fuser/transfer/waste) are still counted in
-- garantie_claims but no longer valued at a toner price. Adds claim_restwert_gesamt
-- (incl. parts) for transparency. CREATE OR REPLACE: appends one column.
CREATE OR REPLACE VIEW insights.vw_lagebericht AS
SELECT
    (SELECT count(*) FROM insights.vw_warranty_assessment WHERE warranty_class = 'claim')        AS garantie_claims,
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim' AND cartridge_serial IS NOT NULL)                          AS garantie_claims_serial,
    (SELECT round(avg(pct_of_oem)) FROM insights.vw_warranty_assessment WHERE warranty_class = 'claim') AS claim_schnitt_pct,
    -- toner-only residual sum (colour present) — matches the toner-price basis
    (SELECT round(sum(GREATEST(0, 1 - LEAST(pct_of_oem, 100) / 100.0))::numeric, 1)
        FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim' AND colorant IS NOT NULL AND colorant <> '')              AS claim_restwert_summe,
    (SELECT count(*) FROM insights.vw_warranty_assessment WHERE warranty_class = 'negotiation')   AS verhandlung_kandidaten,
    (SELECT count(*) FROM insights.vw_part_early_failures)                                        AS ersatzteil_fruehausfaelle,
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
    -- toner-only claim count (the subset the € applies to)
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim' AND colorant IS NOT NULL AND colorant <> '')              AS garantie_claims_toner;
