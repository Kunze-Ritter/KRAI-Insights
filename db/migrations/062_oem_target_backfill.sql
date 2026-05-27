-- 062_oem_target_backfill.sql
-- OEM-Soll-Backfill fuer die Garantie- UND Standzeit-Bewertung.
--
-- Problem: vbm_lifecycle_events.oem_target_pages (die OEM-Soll-Reichweite je Toner-
-- Zyklus) ist nur bei ~14 % der Ereignisse gesetzt (28.312 / 199.170) — stammt aus
-- der alten, engen Radix-Artikel-Quelle. Dadurch "sieht" sowohl vw_warranty_assessment
-- als auch vw_toner_yield_vs_oem nur 14 % der Tonerwechsel. 20.840 Ereignisse mit
-- echtem Seitenlauf (HP 15.258 / KM 3.014 / Lexmark 2.358 / Kyocera 202) bleiben
-- unbewertet, OBWOHL die OEM-Reichweiten seit dem VBM-Crawler vorliegen.
--
-- Loesung: ein leichtgewichtiger Modell-Ebene-Lookup (Toner-Soll je Modell x Farbe),
-- der die teure Per-Geraet-Matching-View vw_device_supplies EINMALIG materialisiert
-- (nicht pro Event joinen — Performance-Lektion aus Migration 056). vw_vbm_lifecycle
-- faellt dann per COALESCE auf diesen Modell-Soll zurueck, wo der gespeicherte Wert
-- fehlt. Wirkung propagiert automatisch in Garantie + Yield (beide lesen oem_target_pages
-- aus vw_vbm_lifecycle).
--
-- FORMEL-ENTSCHEIDUNG (wichtig): Ein Modell hat oft 5-10 Toner-SKUs (Starter/Standard/
-- High/XL) mit Ø 7,95x Spreizung (z. B. Lexmark CX962se: 15k / 47,7k / 225k Seiten).
-- Ein einzelner Wert waere unzuverlaessig: MIN (Starter) wuerde echte Claims uebersehen,
-- MAX (XL) wuerde ueber-claimen. Wir nehmen den MEDIAN als Soll (robust; fuer die
-- Yield-Statistik ueber viele Geraete mittelt sich das Rauschen weg) und fuehren
-- min/max + Spread mit, damit Garantie-Claims aus rauschigen Referenzen spaeter
-- getiert werden koennen (statt blind in die Headline). Der gespeicherte Radix-Wert
-- behaelt Vorrang (COALESCE), d. h. die bisherigen 28k Bewertungen aendern sich NICHT.
--
-- SCOPE: HP / Lexmark / Kyocera (ueber vw_device_supplies = ~85 % der Luecke). KM hat
-- KEINE per-Modell-Kompatibilitaet (Excel-Pfad, model_family-Codename) -> KM-Toner-Soll
-- braucht eine eigene bizhub->KM-Familie-Bruecke (separater Schritt, dokumentiert).

-- 1) Materialisierter Modell-Toner-Soll (einmalige Berechnung aus der schweren View).
CREATE TABLE IF NOT EXISTS insights.model_toner_oem (
    model_display   varchar(255) NOT NULL,
    color_channel   varchar(8)   NOT NULL,   -- bw / c / m / y
    oem_min         integer,
    oem_median      integer,
    oem_max         integer,
    sku_count       integer,
    is_mono_model   boolean,
    ingested_at     timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (model_display, color_channel)
);

TRUNCATE insights.model_toner_oem;
INSERT INTO insights.model_toner_oem
    (model_display, color_channel, oem_min, oem_median, oem_max, sku_count, is_mono_model)
WITH t AS (
    SELECT model_display, color_channel, nominal_lifetime_pages
    FROM insights.vw_device_supplies
    WHERE part_category = 'toner' AND nominal_lifetime_pages > 0
      AND color_channel IN ('bw', 'c', 'm', 'y')
),
mono AS (
    SELECT model_display, bool_and(color_channel = 'bw') AS is_mono
    FROM t GROUP BY model_display
)
SELECT t.model_display, t.color_channel,
       min(t.nominal_lifetime_pages)::int,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY t.nominal_lifetime_pages))::int,
       max(t.nominal_lifetime_pages)::int,
       count(*)::int,
       bool_or(m.is_mono)
FROM t JOIN mono m USING (model_display)
GROUP BY t.model_display, t.color_channel;

-- 2) vw_vbm_lifecycle: oem_target_pages faellt auf den Modell-Median zurueck.
--    Definition wortgetreu uebernommen; GEAENDERT: base joint devices_unified +
--    model_toner_oem; oem_target_pages / pct_of_oem / lifespan_rating nutzen jetzt
--    den effektiven Soll (oem_eff); zwei Spalten angehaengt (oem_target_source,
--    oem_target_spread). Spalten 1..24 unveraendert in Reihenfolge -> CREATE OR REPLACE ok.
CREATE OR REPLACE VIEW insights.vw_vbm_lifecycle AS
WITH base AS (
    SELECT e.id, e.source_pkid, e.fleetmgmt_device_id, e.cartridge_serial, e.colorant,
           e.marker_name, e.page_count_at_event, e.sum_bw, e.sum_color, e.pages_since_previous,
           e.diff_bw, e.diff_color, e.coverage_real_pct, e.oem_target_coverage_pct,
           e.oem_target_pages, e.remaining_pages, e.remaining_days, e.snmp_level_new,
           e.level_last, e.level_new, e.contract_id, e.occurred_at, e.source_system, e.ingested_at,
           lag(NULLIF(e.cartridge_serial::text, ''::text)) OVER w AS prev_serial,
           lag(e.level_new) OVER w AS prev_level,
           du.model_display AS dev_model
    FROM insights.vbm_lifecycle_events e
    LEFT JOIN insights.devices_unified du ON du.fleetmgmt_device_id = e.fleetmgmt_device_id
    WINDOW w AS (PARTITION BY e.fleetmgmt_device_id, e.colorant ORDER BY e.occurred_at)
),
enr AS (
    SELECT b.*,
        -- Modell-Soll (Median) nur als Fallback, wo der gespeicherte Wert fehlt
        COALESCE(NULLIF(b.oem_target_pages, 0), mto.oem_median)::integer AS oem_eff,
        CASE WHEN COALESCE(b.oem_target_pages, 0) > 0 THEN 'fleetmgmt'
             WHEN mto.oem_median IS NOT NULL THEN 'modell_median'
             ELSE NULL END AS oem_src,
        CASE WHEN COALESCE(b.oem_target_pages, 0) <= 0 AND mto.oem_min > 0
             THEN round(mto.oem_max::numeric / mto.oem_min, 1) END AS oem_spread
    FROM base b
    LEFT JOIN insights.model_toner_oem mto
      ON mto.model_display = b.dev_model
     AND mto.color_channel = CASE lower(btrim(b.colorant))
            WHEN 'black' THEN 'bw' WHEN 'cyan' THEN 'c'
            WHEN 'magenta' THEN 'm' WHEN 'yellow' THEN 'y'
            WHEN '' THEN 'bw' ELSE NULL END
     -- leere Farbe nur bei Mono-Modellen als schwarz werten (Farb-Modelle: leere
     -- Farbe = Gesamtzaehler, NICHT die Schwarz-Patrone -> nicht mappen)
     AND (lower(btrim(b.colorant)) IN ('black', 'cyan', 'magenta', 'yellow')
          OR (btrim(COALESCE(b.colorant, '')) = '' AND mto.is_mono_model))
)
SELECT id, source_pkid, fleetmgmt_device_id,
    NULLIF(cartridge_serial::text, ''::text)::character varying(100) AS cartridge_serial,
    colorant, marker_name, page_count_at_event, pages_since_previous, coverage_real_pct,
    oem_target_coverage_pct,
    oem_eff AS oem_target_pages,
    remaining_pages, remaining_days, snmp_level_new, level_last, level_new, occurred_at,
    prev_serial::character varying AS prev_serial,
    CASE
        WHEN NULLIF(cartridge_serial::text, ''::text) IS NULL THEN 'no_serial'::text
        WHEN prev_serial IS NOT NULL AND NULLIF(cartridge_serial::text, ''::text) = prev_serial THEN 'reinsert_same'::text
        ELSE 'real_new_cartridge'::text
    END AS classification,
    NULLIF(cartridge_serial::text, ''::text) IS NOT NULL AND (prev_serial IS NULL OR NULLIF(cartridge_serial::text, ''::text) <> prev_serial) AS is_real_change,
    (prev_serial IS NOT NULL AND NULLIF(cartridge_serial::text, ''::text) = prev_serial)
        OR (pages_since_previous IS NOT NULL AND pages_since_previous < 100 AND level_new > COALESCE(level_last, level_new)) AS likely_false_report,
    CASE WHEN oem_eff > 0 AND pages_since_previous > 0
         THEN round(pages_since_previous::numeric / oem_eff::numeric * 100::numeric, 1)
         ELSE NULL::numeric END AS pct_of_oem,
    CASE WHEN oem_eff > 0 AND pages_since_previous > 0 THEN
        CASE
            WHEN (pages_since_previous::numeric / oem_eff::numeric) < 0.7 THEN 'too_few'::text
            WHEN (pages_since_previous::numeric / oem_eff::numeric) <= 1.3 THEN 'on_target'::text
            WHEN (pages_since_previous::numeric / oem_eff::numeric) <= 2.0 THEN 'top_performer'::text
            ELSE 'outlier'::text
        END
        ELSE NULL::text END AS lifespan_rating,
    'fleetmgmt'::character varying AS source_system,
    oem_src AS oem_target_source,
    oem_spread AS oem_target_spread
FROM enr;

-- 3) vw_warranty_assessment: Soll-Quelle + Spread durchreichen und eine Konfidenz-Stufe
--    fuer den OEM-Soll ableiten (oem_konfidenz). So bleibt die Garantie-Headline
--    glaubwuerdig: Radix-belegte Claims = hoch; Modell-Median nur dann hoch, wenn die
--    SKU-Spreizung eng ist (<=2x); breite Spreizung = niedrig (zeigen, nicht headlinen).
--    Definition wortgetreu uebernommen; cyc traegt 2 Spalten mehr, Output haengt 3 an.
CREATE OR REPLACE VIEW insights.vw_warranty_assessment AS
WITH cyc AS (
    SELECT v.fleetmgmt_device_id, v.colorant, v.marker_name, v.cartridge_serial,
        v.occurred_at AS removed_at,
        lag(v.occurred_at) OVER w AS installed_at,
        v.pages_since_previous AS pages,
        v.oem_target_pages AS rated,
        v.pct_of_oem AS pct_seiten_roh,
        v.coverage_real_pct,
        v.oem_target_coverage_pct,
        v.likely_false_report,
        v.classification,
        v.oem_target_source,
        v.oem_target_spread,
        CASE WHEN v.level_last >= 0 AND v.level_last <= 100 THEN round(v.level_last::numeric)
             ELSE NULL::numeric END AS level_last,
        CASE WHEN v.coverage_real_pct > 0.5 AND v.coverage_real_pct <= 100::numeric
                  AND v.oem_target_coverage_pct > 0::numeric AND v.oem_target_pages > 0
                  AND v.pages_since_previous > 0
             THEN round(v.pages_since_previous::numeric * v.coverage_real_pct
                        / (v.oem_target_pages::numeric * v.oem_target_coverage_pct) * 100::numeric, 1)
             ELSE v.pct_of_oem END AS effektiv_pct,
        v.coverage_real_pct > 0.5 AND v.coverage_real_pct <= 100::numeric
            AND v.oem_target_coverage_pct > 0::numeric AS coverage_belegt
    FROM insights.vw_vbm_lifecycle v
    WINDOW w AS (PARTITION BY v.fleetmgmt_device_id, v.colorant, v.marker_name ORDER BY v.occurred_at)
)
SELECT d.customer_name,
    d.customer_city,
    d.manufacturer_canonical,
    d.model_display,
    d.manufacturer_serial AS device_serial,
    d.radix_device_number,
    c.colorant,
    c.marker_name,
    c.cartridge_serial,
    c.installed_at::date AS installed_on,
    c.removed_at::date AS removed_on,
    c.removed_at::date - c.installed_at::date AS age_days,
    c.pages,
    c.rated,
    c.effektiv_pct AS pct_of_oem,
    (c.removed_at::date - c.installed_at::date) <= 365 AS in_time_warranty,
    CASE
        WHEN c.rated IS NULL OR c.rated <= 0 OR c.pages IS NULL OR c.pages <= 0 THEN 'unknown'::text
        WHEN c.pages < 100 OR (c.removed_at::date - c.installed_at::date) = 0 THEN 'artifact'::text
        WHEN c.likely_false_report THEN 'fehlmeldung'::text
        WHEN c.level_last IS NOT NULL AND c.level_last > 20::numeric THEN 'vorzeitiger_tausch'::text
        WHEN (c.removed_at::date - c.installed_at::date) <= 365 AND c.effektiv_pct < 70::numeric THEN 'claim'::text
        WHEN (c.removed_at::date - c.installed_at::date) > 365 AND c.effektiv_pct < 70::numeric THEN 'negotiation'::text
        WHEN (c.removed_at::date - c.installed_at::date) <= 365 THEN 'wear'::text
        ELSE 'normal'::text
    END AS warranty_class,
    'fleetmgmt'::character varying AS source_system,
    c.likely_false_report,
    c.classification AS vbm_classification,
    c.pct_seiten_roh,
    round(c.coverage_real_pct::numeric, 1) AS coverage_real_pct,
    c.coverage_belegt,
    c.level_last,
    c.oem_target_source,
    c.oem_target_spread,
    CASE
        WHEN c.oem_target_source = 'fleetmgmt' THEN 'hoch'
        WHEN c.oem_target_source = 'modell_median' AND COALESCE(c.oem_target_spread, 99) <= 2 THEN 'hoch'
        WHEN c.oem_target_source = 'modell_median' AND COALESCE(c.oem_target_spread, 99) <= 4 THEN 'mittel'
        WHEN c.oem_target_source = 'modell_median' THEN 'niedrig'
        ELSE NULL
    END AS oem_konfidenz
   FROM cyc c
     JOIN insights.devices_unified d ON d.fleetmgmt_device_id = c.fleetmgmt_device_id
  WHERE c.installed_at IS NOT NULL;

-- 4) vw_lagebericht: Headline-Claims nur hoch+mittel Konfidenz (glaubwuerdig), niedrig
--    (rauschige OEM-Referenz, breiter SKU-Spread) separat ausweisen. Definition
--    wortgetreu (inkl. 061-Queue-Filter bei geraete_live); GEAENDERT: Konfidenz-Filter
--    auf den Claim-/Verhandlungs-/Restwert-Subqueries; 1 Spalte angehaengt.
CREATE OR REPLACE VIEW insights.vw_lagebericht AS
WITH gp AS (
    SELECT percentile_cont(0.1::double precision) WITHIN GROUP (ORDER BY (unit_price::double precision)) AS p10,
           percentile_cont(0.5::double precision) WITHIN GROUP (ORDER BY (unit_price::double precision)) AS med,
           percentile_cont(0.9::double precision) WITHIN GROUP (ORDER BY (unit_price::double precision)) AS p90
    FROM insights.cost_events
    WHERE cost_type::text = 'material'::text AND unit_price > 0::numeric
      AND (description ~~* '%toner%'::text OR description ~~* '%patrone%'::text OR description ~~* '%cartridge%'::text)
), resid AS (
    SELECT GREATEST(0::numeric, 1::numeric - LEAST(wa.pct_of_oem, 100::numeric) / 100.0) AS frac,
           COALESCE(CASE WHEN r.n >= 5 THEN r.median_eur ELSE NULL::double precision END, gp.med) AS price_eur
    FROM insights.vw_warranty_assessment wa
    CROSS JOIN gp
    LEFT JOIN insights.vw_toner_price_ref r ON r.mfr::text = wa.manufacturer_canonical::text
    WHERE wa.warranty_class = 'claim'::text AND wa.colorant IS NOT NULL AND wa.colorant::text <> ''::text
      AND wa.oem_konfidenz = ANY (ARRAY['hoch'::text, 'mittel'::text])
)
SELECT
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim'::text AND oem_konfidenz = ANY (ARRAY['hoch'::text, 'mittel'::text])) AS garantie_claims,
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim'::text AND cartridge_serial IS NOT NULL
          AND oem_konfidenz = ANY (ARRAY['hoch'::text, 'mittel'::text])) AS garantie_claims_serial,
    (SELECT round(avg(pct_of_oem)) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim'::text AND oem_konfidenz = ANY (ARRAY['hoch'::text, 'mittel'::text])) AS claim_schnitt_pct,
    (SELECT round(sum(GREATEST(0::numeric, 1::numeric - LEAST(pct_of_oem, 100::numeric) / 100.0)), 1)
        FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim'::text AND colorant IS NOT NULL AND colorant::text <> ''::text
          AND oem_konfidenz = ANY (ARRAY['hoch'::text, 'mittel'::text])) AS claim_restwert_summe,
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'negotiation'::text AND oem_konfidenz = ANY (ARRAY['hoch'::text, 'mittel'::text])) AS verhandlung_kandidaten,
    (SELECT count(DISTINCT device_serial) FROM insights.vw_part_early_failures
        WHERE konfidenz = ANY (ARRAY['hoch'::text, 'mittel'::text])) AS ersatzteil_fruehausfaelle,
    (SELECT round(percentile_cont(0.5::double precision) WITHIN GROUP (ORDER BY (unit_price::double precision)))
        FROM insights.cost_events
        WHERE cost_type::text = 'material'::text AND unit_price > 0::numeric
          AND (description ~~* '%toner%'::text OR description ~~* '%patrone%'::text OR description ~~* '%cartridge%'::text)) AS toner_preis_median,
    (SELECT count(*) FROM insights.vw_billing_risk) AS stille_unter_vertrag,
    (SELECT count(*) FROM insights.vw_customer_device_mismatch WHERE abgleich = 'abweichung'::text) AS kunden_abweichung,
    (SELECT count(*) FROM insights.vw_consumables_due WHERE remaining_days <= 14) AS verbrauch_14d,
    (SELECT count(*) FROM insights.vw_problem_devices) AS problem_geraete,
    (SELECT count(*) FROM insights.devices_unified
        WHERE device_status::text = 'live'::text AND NOT COALESCE(is_queue_artifact, false)) AS geraete_live,
    'insights'::character varying AS source_system,
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim'::text AND colorant IS NOT NULL AND colorant::text <> ''::text
          AND oem_konfidenz = ANY (ARRAY['hoch'::text, 'mittel'::text])) AS garantie_claims_toner,
    (SELECT round(sum(resid.frac::double precision * resid.price_eur)) FROM resid) AS claim_restwert_eur,
    (SELECT round(sum(resid.frac)::double precision * (SELECT gp.p10 FROM gp)) FROM resid) AS claim_restwert_eur_low,
    (SELECT round(sum(resid.frac)::double precision * (SELECT gp.p90 FROM gp)) FROM resid) AS claim_restwert_eur_high,
    (SELECT gp.p10 FROM gp) AS toner_preis_p10,
    (SELECT gp.p90 FROM gp) AS toner_preis_p90,
    (SELECT count(DISTINCT device_serial) FROM insights.vw_part_early_failures
        WHERE konfidenz = 'niedrig'::text) AS ersatzteil_fruehausfaelle_zeitbasiert,
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim'::text AND oem_konfidenz = 'niedrig'::text) AS garantie_claims_niedrig;
