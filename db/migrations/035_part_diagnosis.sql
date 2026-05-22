-- 035_part_diagnosis.sql
-- Link each spare-part install to the diagnostic text of its activity (why was the
-- part installed / what was the symptom). cost_events.radix_activity_id ->
-- activity_notes. Surfaces "for problem X, part Y was fitted" and pairs the
-- early-failure list with the failure diagnosis. (drop + recreate the 3 views.)
DROP VIEW IF EXISTS insights.vw_part_lifetime_stats;
DROP VIEW IF EXISTS insights.vw_part_early_failures;
DROP VIEW IF EXISTS insights.vw_spare_part_events;

CREATE VIEW insights.vw_spare_part_events AS
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
)
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
    an.problem_text AS diagnose,
    ev.invoicing_type, ev.total_eur,
    'radix+fleetmgmt'::varchar AS source_system
FROM ev
LEFT JOIN insights.devices_unified d ON d.manufacturer_serial = ev.device_serial
LEFT JOIN insights.activity_notes an ON an.radix_activity_id = ev.radix_activity_id;

CREATE VIEW insights.vw_part_early_failures AS
SELECT
    customer_name, manufacturer_canonical, model_display, device_serial,
    teiltyp, description, einbau_datum, naechster_tausch AS erneut_getauscht,
    standzeit_tage, standzeit_seiten, diagnose, invoicing_type,
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
