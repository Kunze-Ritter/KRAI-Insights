-- 026_lagebericht.sql
-- Headline KPIs for the value overview + the agent's "Lagebericht" (one cheap row)
-- and a per-manufacturer warranty breakdown (where to focus claims). Warranty-led:
-- the priority is recoverable money. The €-estimate (claims x median toner price)
-- is computed by the consumer and labelled an estimate (few prices are known).
CREATE OR REPLACE VIEW insights.vw_lagebericht AS
SELECT
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim' AND cartridge_serial IS NOT NULL)        AS garantie_claims,
    (SELECT round(avg(pct_of_oem)) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim')                                          AS claim_schnitt_pct,
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

-- Warranty claims/negotiation per manufacturer — where to focus the claims work.
CREATE OR REPLACE VIEW insights.vw_warranty_by_manufacturer AS
SELECT
    manufacturer_canonical AS hersteller,
    count(*) FILTER (WHERE warranty_class = 'claim' AND cartridge_serial IS NOT NULL)       AS garantiefaelle,
    round(avg(pct_of_oem) FILTER (WHERE warranty_class = 'claim'))                          AS claim_schnitt_pct,
    count(*) FILTER (WHERE warranty_class = 'negotiation' AND cartridge_serial IS NOT NULL) AS verhandlung,
    'fleetmgmt'::varchar AS source_system
FROM insights.vw_warranty_assessment
GROUP BY manufacturer_canonical
HAVING count(*) FILTER (WHERE warranty_class IN ('claim', 'negotiation')) > 0
ORDER BY garantiefaelle DESC;
