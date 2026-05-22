-- 038_part_oem_assessment.sql
-- Per-install spare-part assessment against the OEM nominal lifetime (pages).
-- Where we have the manufacturer Soll (part_lifetime_oem, currently Konica Minolta),
-- a part that ran < 70% of its rated pages = premature (warranty), basis "OEM-Soll".
-- Where no OEM Soll exists, fall back to the 1-year time heuristic (re-replaced
-- within 7–365 days), basis "Zeit". The model-median is the reference only when no
-- OEM Soll exists.
-- CREATE OR REPLACE (append new columns) so dependents (vw_lagebericht) stay valid.
DROP VIEW IF EXISTS insights.vw_part_oem_comparison;  -- superseded by per-install OEM cols

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

CREATE OR REPLACE VIEW insights.vw_part_early_failures AS
SELECT
    customer_name, manufacturer_canonical, model_display, device_serial,
    teiltyp, description, einbau_datum, naechster_tausch AS erneut_getauscht,
    standzeit_tage, standzeit_seiten, diagnose, invoicing_type,
    'radix+fleetmgmt'::varchar AS source_system,
    oem_nominal_seiten, pct_vom_oem,
    CASE WHEN oem_nominal_seiten IS NOT NULL AND standzeit_seiten IS NOT NULL
         THEN 'OEM-Soll (Seiten)' ELSE 'Zeit (1 Jahr)' END AS basis
FROM insights.vw_spare_part_events
WHERE teiltyp NOT IN ('Toner', 'unbekannt')
  AND (
        (oem_nominal_seiten IS NOT NULL AND standzeit_seiten IS NOT NULL
            AND standzeit_tage >= 7 AND pct_vom_oem < 70)
     OR ((oem_nominal_seiten IS NULL OR standzeit_seiten IS NULL)
            AND standzeit_tage BETWEEN 7 AND 365)
      )
ORDER BY pct_vom_oem ASC NULLS LAST, standzeit_tage ASC;

CREATE OR REPLACE VIEW insights.vw_part_lifetime_stats AS
SELECT
    s.manufacturer_canonical AS hersteller, s.model_display AS modell, s.teiltyp,
    count(*)                                                            AS stichproben,
    count(DISTINCT s.device_serial)                                     AS geraete,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY s.standzeit_tage)) AS median_standzeit_tage,
    count(s.standzeit_seiten)                                           AS stichproben_seiten,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY s.standzeit_seiten)
          FILTER (WHERE s.standzeit_seiten IS NOT NULL))                AS median_standzeit_seiten,
    'radix+fleetmgmt'::varchar AS source_system,
    max(s.oem_nominal_seiten)                                           AS oem_nominal_seiten
FROM insights.vw_spare_part_events s
WHERE s.teiltyp NOT IN ('Toner', 'unbekannt') AND s.standzeit_tage >= 30
GROUP BY s.manufacturer_canonical, s.model_display, s.teiltyp
HAVING count(*) >= 5
ORDER BY median_standzeit_tage ASC;
