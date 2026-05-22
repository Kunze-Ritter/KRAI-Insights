-- 036_lagebericht_parts.sql
-- Add spare-part early failures to the headline KPIs (Geld-zurückholen covers parts
-- too, not just toner). (drop + recreate; no dependents.)
DROP VIEW IF EXISTS insights.vw_lagebericht;
CREATE VIEW insights.vw_lagebericht AS
SELECT
    (SELECT count(*) FROM insights.vw_warranty_assessment WHERE warranty_class = 'claim')        AS garantie_claims,
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim' AND cartridge_serial IS NOT NULL)                          AS garantie_claims_serial,
    (SELECT round(avg(pct_of_oem)) FROM insights.vw_warranty_assessment WHERE warranty_class = 'claim') AS claim_schnitt_pct,
    (SELECT round(sum(GREATEST(0, 1 - LEAST(pct_of_oem, 100) / 100.0))::numeric, 1)
        FROM insights.vw_warranty_assessment WHERE warranty_class = 'claim')                      AS claim_restwert_summe,
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
    'insights'::varchar AS source_system;
