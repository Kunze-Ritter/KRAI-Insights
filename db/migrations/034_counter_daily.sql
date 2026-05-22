-- 034_counter_daily.sql
-- Day-accurate spare-part lifetime (replaces the monthly approximation from 032).
-- A part is installed on a specific DAY (ticket resolved) and fails on a specific
-- day — so we read the page counter at the NEAREST reading to that exact day, not
-- a monthly max. device_counter_daily = one row per device-day with a reading
-- (~4.9M rows); insights.page_at(device, date) returns the nearest reading.
CREATE TABLE IF NOT EXISTS insights.device_counter_daily (
    fleetmgmt_device_id INTEGER NOT NULL,
    day                 DATE    NOT NULL,
    page_count          INTEGER,
    PRIMARY KEY (fleetmgmt_device_id, day)
);

-- Nearest page-counter reading to a given day (closest before OR after).
CREATE OR REPLACE FUNCTION insights.page_at(dev integer, d date)
RETURNS integer LANGUAGE sql STABLE AS $fn$
    SELECT z.page_count FROM (
        (SELECT page_count, day FROM insights.device_counter_daily
            WHERE fleetmgmt_device_id = dev AND day <= d ORDER BY day DESC LIMIT 1)
        UNION ALL
        (SELECT page_count, day FROM insights.device_counter_daily
            WHERE fleetmgmt_device_id = dev AND day > d ORDER BY day ASC LIMIT 1)
    ) z
    WHERE d IS NOT NULL
    ORDER BY abs(z.day - d) LIMIT 1
$fn$;

DROP VIEW IF EXISTS insights.vw_part_lifetime_stats;
DROP VIEW IF EXISTS insights.vw_part_early_failures;
DROP VIEW IF EXISTS insights.vw_spare_part_events;
DROP TABLE IF EXISTS insights.device_counter_monthly;

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
    insights.page_at(d.fleetmgmt_device_id, ev.einbau_datum)     AS seiten_einbau,
    insights.page_at(d.fleetmgmt_device_id, ev.naechster_tausch) AS seiten_tausch,
    CASE WHEN insights.page_at(d.fleetmgmt_device_id, ev.einbau_datum) IS NOT NULL
              AND insights.page_at(d.fleetmgmt_device_id, ev.naechster_tausch)
                  > insights.page_at(d.fleetmgmt_device_id, ev.einbau_datum)
         THEN insights.page_at(d.fleetmgmt_device_id, ev.naechster_tausch)
              - insights.page_at(d.fleetmgmt_device_id, ev.einbau_datum) END AS standzeit_seiten,
    ev.invoicing_type, ev.total_eur,
    'radix+fleetmgmt'::varchar AS source_system
FROM ev
LEFT JOIN insights.devices_unified d ON d.manufacturer_serial = ev.device_serial;

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
