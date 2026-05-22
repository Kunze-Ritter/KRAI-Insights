-- 031_spare_part_lifecycle.sql
-- Spare-part (and non-toner consumable) lifecycle from Radix cost events. Unlike
-- toner, field parts have NO rated page life — just a ~1-year warranty. We derive
-- the REALIZED lifetime as the interval between consecutive installs of the SAME
-- article on the SAME device (the old one failed when the new one went in). From
-- that: early-failure detection (re-replaced within warranty -> reclaim) AND a
-- per-(model x part type) lifetime model (predict next failure -> PM).
--
-- NOTE: this complements the toner warranty analysis (vw_warranty_assessment,
-- FleetMgmt VBM) — see docs/garantie.md. Source here is Radix material lines.

-- Reusable part-type classifier from the (German/English) article description.
CREATE OR REPLACE FUNCTION insights.part_type(p text) RETURNS text LANGUAGE sql IMMUTABLE AS $fn$
    SELECT CASE
        WHEN p IS NULL THEN 'unbekannt'
        WHEN p ILIKE '%toner%' OR p ILIKE '%patrone%' OR p ILIKE '%cartridge%' THEN 'Toner'
        WHEN p ILIKE '%waste%' OR p ILIKE '%resttoner%' OR p ILIKE '%auffang%' THEN 'Resttonerbehälter'
        WHEN p ILIKE '%fixier%' OR p ILIKE '%fuser%' OR p ILIKE '%heizung%' OR p ILIKE '%fusing%' THEN 'Fixiereinheit'
        WHEN p ILIKE '%trommel%' OR p ILIKE '%drum%' OR p ILIKE '%image unit%' OR p ILIKE '%imaging%' THEN 'Trommel/Drum'
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

-- One row per material install, with part type, device context, and the days to
-- the NEXT install of the same article on the same device (= realized lifetime).
CREATE OR REPLACE VIEW insights.vw_spare_part_events AS
WITH ev AS (
    SELECT
        ce.device_serial, ce.article_code, ce.description,
        insights.part_type(ce.description) AS teiltyp,
        ce.occurred_at::date AS einbau_datum,
        ce.invoicing_type, ce.total_eur,
        lead(ce.occurred_at::date) OVER (
            PARTITION BY ce.device_serial, ce.article_code ORDER BY ce.occurred_at
        ) AS naechster_tausch
    FROM insights.cost_events ce
    WHERE ce.cost_type = 'material' AND ce.device_serial IS NOT NULL
      AND ce.article_code IS NOT NULL AND ce.occurred_at IS NOT NULL
)
SELECT
    d.customer_name, d.manufacturer_canonical, d.model_display,
    ev.device_serial, ev.teiltyp, ev.description, ev.article_code,
    ev.einbau_datum, ev.naechster_tausch,
    (ev.naechster_tausch - ev.einbau_datum) AS standzeit_tage,
    ev.invoicing_type, ev.total_eur,
    'radix+fleetmgmt'::varchar AS source_system
FROM ev
LEFT JOIN insights.devices_unified d ON d.manufacturer_serial = ev.device_serial;

-- Early failures: a part re-replaced within the ~1-year warranty (7–365 days; the
-- <7-day band is same-incident noise). Toner is excluded (own analysis).
CREATE OR REPLACE VIEW insights.vw_part_early_failures AS
SELECT
    customer_name, manufacturer_canonical, model_display, device_serial,
    teiltyp, description, einbau_datum, naechster_tausch AS erneut_getauscht,
    standzeit_tage, invoicing_type,
    'radix+fleetmgmt'::varchar AS source_system
FROM insights.vw_spare_part_events
WHERE teiltyp NOT IN ('Toner', 'unbekannt')
  AND standzeit_tage BETWEEN 7 AND 365
ORDER BY standzeit_tage ASC;

-- Lifetime model per (manufacturer x model x part type): median realized lifetime
-- from intervals >= 30 days, only where we have enough samples (>= 5) to be useful.
CREATE OR REPLACE VIEW insights.vw_part_lifetime_stats AS
SELECT
    manufacturer_canonical AS hersteller, model_display AS modell, teiltyp,
    count(*)                                                         AS stichproben,
    count(DISTINCT device_serial)                                   AS geraete,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY standzeit_tage)) AS median_standzeit_tage,
    round(avg(standzeit_tage))                                      AS schnitt_standzeit_tage,
    min(standzeit_tage)                                             AS min_tage,
    max(standzeit_tage)                                             AS max_tage,
    'radix+fleetmgmt'::varchar AS source_system
FROM insights.vw_spare_part_events
WHERE teiltyp NOT IN ('Toner', 'unbekannt') AND standzeit_tage >= 30
GROUP BY manufacturer_canonical, model_display, teiltyp
HAVING count(*) >= 5
ORDER BY median_standzeit_tage ASC;
