-- 032_part_lifetime_pages.sql
-- Spare-part lifetime in PAGES (not just days). A monthly page-counter timeline
-- per device (downsampled from ACCSNMPHISTORY) lets us read the device's page
-- count at install and at the next replacement; the difference is the realized
-- lifetime in pages — far more meaningful than calendar days for usage-driven wear.
CREATE TABLE IF NOT EXISTS insights.device_counter_monthly (
    fleetmgmt_device_id INTEGER NOT NULL,
    month               DATE    NOT NULL,
    page_count          INTEGER,
    PRIMARY KEY (fleetmgmt_device_id, month)
);

-- Recreate the spare-part views to add the page-based lifetime (drop dependents
-- first; they are rebuilt right after).
DROP VIEW IF EXISTS insights.vw_part_lifetime_stats;
DROP VIEW IF EXISTS insights.vw_part_early_failures;
DROP VIEW IF EXISTS insights.vw_spare_part_events;

CREATE VIEW insights.vw_spare_part_events AS
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
    cm_in.page_count  AS seiten_einbau,
    cm_next.page_count AS seiten_tausch,
    CASE WHEN cm_in.page_count IS NOT NULL AND cm_next.page_count IS NOT NULL
              AND cm_next.page_count > cm_in.page_count
         THEN cm_next.page_count - cm_in.page_count END AS standzeit_seiten,
    ev.invoicing_type, ev.total_eur,
    'radix+fleetmgmt'::varchar AS source_system
FROM ev
LEFT JOIN insights.devices_unified d ON d.manufacturer_serial = ev.device_serial
LEFT JOIN insights.device_counter_monthly cm_in
    ON cm_in.fleetmgmt_device_id = d.fleetmgmt_device_id
   AND cm_in.month = date_trunc('month', ev.einbau_datum)::date
LEFT JOIN insights.device_counter_monthly cm_next
    ON cm_next.fleetmgmt_device_id = d.fleetmgmt_device_id
   AND cm_next.month = date_trunc('month', ev.naechster_tausch)::date;

-- Early failures: re-replaced within the ~1-year warranty (7–365 days). Toner out.
CREATE VIEW insights.vw_part_early_failures AS
SELECT
    customer_name, manufacturer_canonical, model_display, device_serial,
    teiltyp, description, einbau_datum, naechster_tausch AS erneut_getauscht,
    standzeit_tage, standzeit_seiten, invoicing_type,
    'radix+fleetmgmt'::varchar AS source_system
FROM insights.vw_spare_part_events
WHERE teiltyp NOT IN ('Toner', 'unbekannt')
  AND standzeit_tage BETWEEN 7 AND 365
ORDER BY standzeit_tage ASC;

-- Lifetime model per (manufacturer x model x part type): median lifetime in DAYS
-- and in PAGES (where counter data exists), from intervals >= 30 days, >= 5 samples.
CREATE VIEW insights.vw_part_lifetime_stats AS
SELECT
    manufacturer_canonical AS hersteller, model_display AS modell, teiltyp,
    count(*)                                                            AS stichproben,
    count(DISTINCT device_serial)                                       AS geraete,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY standzeit_tage))  AS median_standzeit_tage,
    count(standzeit_seiten)                                             AS stichproben_seiten,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY standzeit_seiten)
          FILTER (WHERE standzeit_seiten IS NOT NULL))                  AS median_standzeit_seiten,
    'radix+fleetmgmt'::varchar AS source_system
FROM insights.vw_spare_part_events
WHERE teiltyp NOT IN ('Toner', 'unbekannt') AND standzeit_tage >= 30
GROUP BY manufacturer_canonical, model_display, teiltyp
HAVING count(*) >= 5
ORDER BY median_standzeit_tage ASC;
