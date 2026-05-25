-- 050_km_image_unit_teiltyp.sql
-- KM-Excel-Kategorie 'image_unit_color' → Teiltyp 'Imaging Unit' (statt 'Trommel/Drum').
--
-- Offener Punkt aus 048/049: die KM-Excel führt 'image_unit_color' (12 Zeilen,
-- Median ~155.000 S.) - das sind Konica-Minolta-bizhub-Color-Imaging-Units
-- (IU-xxx = Fotoleiter + Entwickler in EINEM Bauteil), also fachlich genau eine
-- Imaging Unit, KEINE reine Trommel. In 048/049 vorerst auf 'Trommel/Drum'
-- belassen (KM-Semantik unverifiziert). Verifiziert (2026-05-25):
--   * Ist-Seite: 356 KM-Ersatzteil-Events / 149 Geräte sind bereits
--     teiltyp='Imaging Unit' (part_type() erkennt "Bildeinheit"/"Imaging Unit").
--   * Sie jointen bisher NICHT auf KM-OEM-Soll (das lag als 'Trommel/Drum' vor)
--     und verwässerten zugleich den KM-Trommel-Median (260k mit 155k vermischt).
-- Remap behebt beides: 356 Events bekommen OEM-Soll-Grundlage, Trommel-Median
-- wird sauber. part_type() ist bereits korrekt (049) - hier nur das OEM-CASE.

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
                WHEN 'image_unit_color' THEN 'Imaging Unit'
                WHEN 'adf' THEN 'Scanner/ADF'
                WHEN 'transfer_belt' THEN 'Transfer'
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
