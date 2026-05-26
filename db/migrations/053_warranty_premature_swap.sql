-- 053_warranty_premature_swap.sql
-- CREDIBILITY FIX (user-found, 2026-05-26): the warranty-claim logic flagged any
-- cartridge that printed < 70 % of its rated (coverage-adjusted) yield as a "claim"
-- — WITHOUT checking whether the cartridge was actually EMPTY when removed. A
-- cartridge swapped while still half-full prints few pages too, and was wrongly
-- counted as a premature-failure claim.
--
-- Measured on 2025: of 176 serial-backed claims, only 48 (27 %) were genuinely
-- (near-)empty at removal; 115 (65 %) were swapped while > 30 % full (avg fill 49 %).
-- Example "Weiss_Automotive": 95 "claims", but the April spike (53) was a bulk swap
-- of half-full cartridges (avg 44 % remaining) — not defects.
--
-- THE DISCRIMINATOR: ACCMARKERREFILL records the OUTGOING cartridge's fill level
-- (`vw_vbm_lifecycle.level_last`, 0..100 %). A genuine early failure = empty
-- (level_last low) yet delivered < 70 % of rated toner → defective / short-fill.
-- A high fill level at removal = the cartridge still had toner → it was swapped
-- early, not defective.
--
-- TWO outcomes, both valuable:
--   1) `claim`/`negotiation` now require the cartridge to have been (near-)empty
--      (level_last <= 20, or unknown) → honest, submittable premature-failure pool.
--   2) NEW class `vorzeitiger_tausch` = cartridge removed with > 20 % toner left.
--      This is WASTE: the customer/MSP throws away usable toner. `vw_toner_waste`
--      quantifies the wasted € per customer (remaining fill × toner price) — an
--      own recovery / advisory angle ("Kunde wirft Toner weg").
--
-- level_last is FleetMgmt SNMP — clamped to a sane 0..100; outside / NULL = unknown
-- (then we keep the old behaviour, i.e. claim-eligible, to not lose genuine claims
-- where the fleet didn't report a fill level, e.g. some KM/Kyocera).

CREATE OR REPLACE VIEW insights.vw_warranty_assessment AS
WITH cyc AS (
    SELECT
        v.fleetmgmt_device_id, v.colorant, v.marker_name, v.cartridge_serial,
        v.occurred_at                              AS removed_at,
        LAG(v.occurred_at) OVER w                  AS installed_at,
        v.pages_since_previous                     AS pages,
        v.oem_target_pages                         AS rated,
        v.pct_of_oem                               AS pct_seiten_roh,
        v.coverage_real_pct, v.oem_target_coverage_pct,
        v.likely_false_report, v.classification,
        -- Füllstand der ausgehenden Kartusche beim Tausch (0..100 %); sonst NULL.
        CASE WHEN v.level_last BETWEEN 0 AND 100 THEN round(v.level_last::numeric) END AS level_last,
        CASE
            WHEN v.coverage_real_pct > 0.5 AND v.coverage_real_pct <= 100
                 AND v.oem_target_coverage_pct > 0 AND v.oem_target_pages > 0
                 AND v.pages_since_previous > 0
            THEN round((v.pages_since_previous::numeric * v.coverage_real_pct)
                       / (v.oem_target_pages * v.oem_target_coverage_pct) * 100, 1)
            ELSE v.pct_of_oem
        END AS effektiv_pct,
        (v.coverage_real_pct > 0.5 AND v.coverage_real_pct <= 100
            AND v.oem_target_coverage_pct > 0) AS coverage_belegt
    FROM insights.vw_vbm_lifecycle v
    WINDOW w AS (PARTITION BY v.fleetmgmt_device_id, v.colorant, v.marker_name ORDER BY v.occurred_at)
)
SELECT
    d.customer_name, d.customer_city, d.manufacturer_canonical, d.model_display,
    d.manufacturer_serial AS device_serial, d.radix_device_number,
    c.colorant, c.marker_name, c.cartridge_serial,
    c.installed_at::date AS installed_on, c.removed_at::date AS removed_on,
    (c.removed_at::date - c.installed_at::date) AS age_days,
    c.pages, c.rated,
    c.effektiv_pct AS pct_of_oem,           -- coverage-adjusted toner yield (drives € + class)
    (c.removed_at::date - c.installed_at::date) <= 365 AS in_time_warranty,
    CASE
        WHEN c.rated IS NULL OR c.rated <= 0 OR c.pages IS NULL OR c.pages <= 0 THEN 'unknown'
        WHEN c.pages < 100 OR (c.removed_at::date - c.installed_at::date) = 0 THEN 'artifact'
        WHEN c.likely_false_report THEN 'fehlmeldung'
        -- NEU: noch >20 % voll rausgenommen = kein Defekt, sondern Verschwendung
        WHEN c.level_last IS NOT NULL AND c.level_last > 20 THEN 'vorzeitiger_tausch'
        -- Claim/negotiation nur, wenn (nahezu) leer ODER Füllstand unbekannt:
        WHEN (c.removed_at::date - c.installed_at::date) <= 365 AND c.effektiv_pct < 70 THEN 'claim'
        WHEN (c.removed_at::date - c.installed_at::date) >  365 AND c.effektiv_pct < 70 THEN 'negotiation'
        WHEN (c.removed_at::date - c.installed_at::date) <= 365 THEN 'wear'
        ELSE 'normal'
    END AS warranty_class,
    'fleetmgmt'::varchar AS source_system,
    c.likely_false_report,
    c.classification AS vbm_classification,
    c.pct_seiten_roh,
    round(c.coverage_real_pct::numeric, 1) AS coverage_real_pct,
    c.coverage_belegt,
    c.level_last                            -- Füllstand der getauschten Kartusche (NULL = unbekannt) — neue Spalte am Ende (CREATE OR REPLACE)
FROM cyc c
JOIN insights.devices_unified d ON d.fleetmgmt_device_id = c.fleetmgmt_device_id
WHERE c.installed_at IS NOT NULL;

-- Toner-Verschwendung je Kunde: Kartuschen, die mit >20 % Restfüllung getauscht
-- wurden (= weggeworfener Toner). Geschätzter Wert = Restfüllung × Tonerpreis je
-- Hersteller (Fallback Gesamt-Median aus vw_toner_price_ref). Aktionsliste:
-- "hier wirft der Kunde Toner weg" → Beratung / Abrechnung / Vertragsgespräch.
CREATE OR REPLACE VIEW insights.vw_toner_waste AS
WITH gmed AS (
    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY median_eur) AS g
    FROM insights.vw_toner_price_ref
)
SELECT
    a.customer_name,
    a.customer_city,
    a.manufacturer_canonical,
    count(*)                                                   AS vorzeitige_tausche,
    count(DISTINCT a.device_serial)                            AS geraete,
    round(avg(a.level_last))                                   AS avg_restfuellung_pct,
    round(sum(a.level_last) / 100.0)                           AS verworfene_kartuschen_aequiv,
    round(sum((a.level_last / 100.0)
              * COALESCE(p.median_eur, (SELECT g FROM gmed))))::int AS verschwendung_eur
FROM insights.vw_warranty_assessment a
LEFT JOIN insights.vw_toner_price_ref p ON p.mfr = a.manufacturer_canonical
WHERE a.warranty_class = 'vorzeitiger_tausch'
GROUP BY a.customer_name, a.customer_city, a.manufacturer_canonical;
