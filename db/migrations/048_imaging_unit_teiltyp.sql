-- 048_imaging_unit_teiltyp.sql
-- Imaging Unit als EIGENER Teiltyp (Fachkorrektur, User 2026-05-24).
--
-- Eine Imaging Unit = Drum + Developer in EINEM Bauteil (z. B. Lexmark MS/MX-Mono:
-- "Belichtungseinheit"). Bei anderen Modellen sind Trommel (Fotoleiter) und
-- Entwicklereinheit GETRENNT. Bisher haben beide Join-Seiten Imaging Units
-- faelschlich mit reinen Trommeln vermischt:
--   * Crawler/Extractor: imaging_unit/imaging_kit -> 'drum' (jetzt -> 'imaging_unit')
--   * insights.part_type() (seit 031): '%image unit%'/'%imaging%' -> 'Trommel/Drum'
-- Diese Migration trennt das sauber in den neuen Teiltyp 'Imaging Unit'.
--
-- Wirkt auf BEIDE Seiten des OEM-Soll-Joins:
--   1) insights.part_type() bekommt einen 'Imaging Unit'-Zweig (VOR Toner/Trommel),
--      und der Trommel-Zweig erkennt zusaetzlich 'fotoleiter'/'photoconductor'.
--   2) vw_spare_part_events: das OEM-part_category->teiltyp-CASE mappt die neue
--      Kategorie 'imaging_unit' -> 'Imaging Unit'.
-- part_type() ist eine Funktion -> alle Views, die sie aufrufen, nutzen die neue
-- Logik sofort. vw_spare_part_events behaelt dieselben Ausgabespalten (nur das
-- interne oem-CTE aendert sich) -> CREATE OR REPLACE haelt Dependents gueltig.
--
-- HINWEIS KM: die KM-Excel-Kategorie 'image_unit_color' bleibt hier bewusst auf
-- 'Trommel/Drum' (KM-Produktsemantik nicht verifiziert) - separat zu pruefen.

-- 1) part_type() ------------------------------------------------------------------
CREATE OR REPLACE FUNCTION insights.part_type(p text) RETURNS text LANGUAGE sql IMMUTABLE AS $fn$
    SELECT CASE
        WHEN p IS NULL THEN 'unbekannt'
        -- Imaging Unit (Drum+Developer kombiniert) VOR Toner/Trommel/Entwickler,
        -- sonst faengt '%cartridge%' / '%drum%' / '%develop%' es vorher ab.
        WHEN p ILIKE '%imaging unit%' OR p ILIKE '%image unit%' OR p ILIKE '%imaging kit%'
             OR p ILIKE '%belichtungseinheit%' OR p ILIKE '%bildtrommel%'
             OR p ILIKE '%bildeinheit%' OR p ILIKE '%abbildungseinheit%' THEN 'Imaging Unit'
        WHEN p ILIKE '%toner%' OR p ILIKE '%patrone%' OR p ILIKE '%cartridge%' THEN 'Toner'
        WHEN p ILIKE '%waste%' OR p ILIKE '%resttoner%' OR p ILIKE '%auffang%' THEN 'Resttonerbehälter'
        WHEN p ILIKE '%fixier%' OR p ILIKE '%fuser%' OR p ILIKE '%heizung%' OR p ILIKE '%fusing%' THEN 'Fixiereinheit'
        WHEN p ILIKE '%trommel%' OR p ILIKE '%drum%' OR p ILIKE '%fotoleiter%' OR p ILIKE '%photoconductor%' THEN 'Trommel/Drum'
        WHEN p ILIKE '%transfer%' OR p ILIKE '%itb%' THEN 'Transfer'
        WHEN p ILIKE '%entwickl%' OR p ILIKE '%develop%' THEN 'Entwickler'
        WHEN p ILIKE '%walze%' OR p ILIKE '%roller%' OR p ILIKE '%pickup%' OR p ILIKE '%separation%' THEN 'Walze/Roller'
        WHEN p ILIKE '%board%' OR p ILIKE '%formatter%' OR p ILIKE '%netzteil%' OR p ILIKE '%hdd%'
             OR p ILIKE '%festplatte%' OR p ILIKE '%mainboard%' THEN 'Elektronik/Board'
        WHEN p ILIKE '%scanner%' OR p ILIKE '%flatbed%' OR p ILIKE '%adf%' THEN 'Scanner/ADF'
        WHEN p ILIKE '%laser%' OR p ILIKE '%lsu%' THEN 'Laser/LSU'
        ELSE 'sonstige'
    END
$fn$;

-- 2) vw_spare_part_events: OEM-CASE um 'imaging_unit' -> 'Imaging Unit' erweitern --
--    (sonst identisch zu Migration 038 - gleiche Ausgabespalten).
CREATE OR REPLACE VIEW insights.vw_spare_part_events AS
WITH ev AS (
    SELECT
        ce.device_serial, ce.article_code, ce.description, ce.radix_activity_id,
        insights.part_type(ce.description) AS teiltyp,
        ce.occurred_at::date AS einbau_datum,
        ce.invoicing_type, ce.total_eur,
        lead(ce.occurred_at::date) OVER (
            PARTITION BY ce.device_serial, ce.article_code ORDER BY ce.occurred_at
        ) AS naechster_tausch
    FROM insights.cost_events ce
    WHERE ce.cost_type = 'material' AND ce.device_serial IS NOT NULL
      AND ce.article_code IS NOT NULL AND ce.occurred_at IS NOT NULL
),
base AS (
    SELECT
        d.customer_name, d.manufacturer_canonical, d.model_display,
        ev.device_serial, ev.teiltyp, ev.description, ev.article_code, ev.radix_activity_id,
        ev.einbau_datum, ev.naechster_tausch,
        (ev.naechster_tausch - ev.einbau_datum) AS standzeit_tage,
        insights.page_at(d.fleetmgmt_device_id, ev.einbau_datum)     AS seiten_einbau,
        insights.page_at(d.fleetmgmt_device_id, ev.naechster_tausch) AS seiten_tausch,
        CASE WHEN insights.page_at(d.fleetmgmt_device_id, ev.einbau_datum) IS NOT NULL
                  AND insights.page_at(d.fleetmgmt_device_id, ev.naechster_tausch)
                      > insights.page_at(d.fleetmgmt_device_id, ev.einbau_datum)
             THEN insights.page_at(d.fleetmgmt_device_id, ev.naechster_tausch)
                  - insights.page_at(d.fleetmgmt_device_id, ev.einbau_datum) END AS standzeit_seiten,
        an.problem_text AS diagnose, ev.invoicing_type, ev.total_eur
    FROM ev
    LEFT JOIN insights.devices_unified d ON d.manufacturer_serial = ev.device_serial
    LEFT JOIN insights.activity_notes an ON an.radix_activity_id = ev.radix_activity_id
),
oem AS (
    SELECT manufacturer, teiltyp,
           round(percentile_cont(0.5) WITHIN GROUP (ORDER BY nominal_lifetime_pages)) AS oem_nominal
    FROM (
        SELECT manufacturer, nominal_lifetime_pages,
            CASE part_category
                WHEN 'fuser' THEN 'Fixiereinheit' WHEN 'drum' THEN 'Trommel/Drum'
                WHEN 'imaging_unit' THEN 'Imaging Unit'
                WHEN 'image_unit_color' THEN 'Trommel/Drum' WHEN 'transfer_belt' THEN 'Transfer'
                WHEN 'transfer_roller' THEN 'Transfer' WHEN 'pickup_roller' THEN 'Walze/Roller'
                WHEN 'developing_unit_bw' THEN 'Entwickler' WHEN 'toner' THEN 'Toner' ELSE NULL
            END AS teiltyp
        FROM insights.part_lifetime_oem
    ) z WHERE teiltyp IS NOT NULL GROUP BY manufacturer, teiltyp
)
SELECT
    base.customer_name, base.manufacturer_canonical, base.model_display,
    base.device_serial, base.teiltyp, base.description, base.article_code, base.radix_activity_id,
    base.einbau_datum, base.naechster_tausch, base.standzeit_tage,
    base.seiten_einbau, base.seiten_tausch, base.standzeit_seiten,
    base.diagnose, base.invoicing_type, base.total_eur,
    'radix+fleetmgmt'::varchar AS source_system,
    o.oem_nominal AS oem_nominal_seiten,
    round(100.0 * base.standzeit_seiten / NULLIF(o.oem_nominal, 0)) AS pct_vom_oem
FROM base
LEFT JOIN oem o ON o.manufacturer ILIKE base.manufacturer_canonical || '%' AND o.teiltyp = base.teiltyp;
