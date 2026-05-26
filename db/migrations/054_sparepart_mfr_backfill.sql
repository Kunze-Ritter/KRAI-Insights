-- 054_sparepart_mfr_backfill.sql
-- DATENQUALITÄT: vw_spare_part_events (und davon abgeleitet vw_part_early_failures /
-- vw_part_lifetime_stats) bezog Hersteller/Modell aus dem Join cost_events.device_serial
-- == devices_unified.manufacturer_serial. Radix-Kostenevents von Geräten, die NICHT
-- in unserer FleetMgmt-Flotte stehen (Radix-only), bekamen so manufacturer_canonical=NULL
-- → ~2.982 Ersatzteil-Ereignisse als "None"/Konfidenz niedrig, obwohl es ganz
-- überwiegend Konica-Minolta-bizhub-Geräte sind (erkennbar am OEM-Code-Präfix der
-- Radix-Seriennummer, z. B. "AA7R021…", "A9JU021…").
--
-- FIX: sicherer Backfill über den OEM-Code-Präfix. Aus devices_unified bauen wir eine
-- EINDEUTIGE Zuordnung (erste 4 Zeichen des manufacturer_model_code → Hersteller, nur
-- wenn dieser Präfix in der Flotte zu GENAU EINEM Hersteller gehört). Greift nur, wenn
-- der Geräte-Join leer blieb (COALESCE bevorzugt den echten Treffer). Konservativ:
-- nicht-eindeutige Präfixe und unbekannte Codes bleiben NULL (kein Raten).
-- Effekt: ~429 bisher herstellerlose Ereignisse werden Konica Minolta zugeordnet und
-- erhalten damit KMs OEM-Soll je Teiltyp (Trommel/Fixierer/… aus der KM-Excel) →
-- Konfidenz steigt von "niedrig" auf "hoch". Page-Daten bleiben NULL (Gerät nicht in
-- FleetMgmt) → diese Fälle laufen über Zeit-/Peer-Tier, nun aber mit Hersteller.
--
-- CREATE OR REPLACE: identische Ausgabespalten + Reihenfolge wie 050; nur der
-- manufacturer-WERT in der base-CTE wird per COALESCE ergänzt.

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
mfr_prefix AS (   -- eindeutiger OEM-Code-Präfix (4 Z.) -> Hersteller, aus der Flotte gelernt
    SELECT substr(manufacturer_model_code, 1, 4) AS pfx, max(manufacturer_canonical) AS mfr
    FROM insights.devices_unified
    WHERE manufacturer_model_code IS NOT NULL AND manufacturer_model_code <> ''
      AND manufacturer_canonical IS NOT NULL
    GROUP BY 1
    HAVING count(DISTINCT manufacturer_canonical) = 1
),
base AS (
    SELECT
        d.customer_name,
        COALESCE(d.manufacturer_canonical, pfx.mfr)::varchar(100) AS manufacturer_canonical,  -- Backfill (Cast: Typ wie Original)
        d.model_display,
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
    LEFT JOIN mfr_prefix pfx ON pfx.pfx = substr(ev.device_serial, 1, 4)
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
