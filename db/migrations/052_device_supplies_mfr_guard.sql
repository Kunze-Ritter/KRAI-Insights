-- 052_device_supplies_mfr_guard.sql
-- Macht den Hersteller-Guard in vw_device_supplies robust + modellpräfix-unabhängig,
-- damit auch Hersteller mit NICHT marken-präfigierten Flotten-Modellnamen greifen.
--
-- HINTERGRUND:
-- Migration 051 prüfte die Hersteller-Zugehörigkeit über das ERSTE Wort des
-- Crawler-Druckernamens: `manufacturer_canonical ILIKE split_part(printer_model,' ',1)||'%'`.
-- Das funktioniert für Lexmark ("Lexmark CX…") und HP ("HP LaserJet …"), wo der
-- Markenname vorne steht. **Kyocera** aber führt seine Flotten-Modelle als
-- "TASKalfa 2508ci", "ECOSYS M3540idn", "FS-2100DN", "2508ci" — OHNE "Kyocera"-
-- Präfix. Da der Crawler-Supply zum exakten Match denselben String tragen muss,
-- wäre split_part(...) = "TASKalfa"/"ECOSYS"/… und der Guard 'Kyocera' ILIKE
-- 'TASKalfa%' = FALSE → Kyocera würde nie matchen.
--
-- FIX: gegen das echte Hersteller-Feld des Supplies prüfen (`ps.manufacturer`,
-- aus part_compatibility/part_lifetime_oem) statt gegen das geratene erste Wort
-- des Druckernamens. Für Lexmark/HP identisches Ergebnis (manufacturer = Marke),
-- für Kyocera korrekt (manufacturer = 'Kyocera', Druckername ohne Präfix).
--
-- Nur die View wird neu erstellt; printer_model_key()/printer_platform_code()
-- (Migration 051) bleiben unverändert.

CREATE OR REPLACE VIEW insights.vw_device_supplies AS
WITH dev AS (
    SELECT
        d.fleetmgmt_device_id,
        d.manufacturer_serial,
        d.radix_device_number,
        d.model_display,
        d.manufacturer_canonical,
        d.device_status,
        insights.printer_model_key(d.model_display)     AS dev_key,
        insights.printer_platform_code(d.model_display) AS platform
    FROM insights.devices_unified d
),
ps AS (  -- Crawler-Supplies inkl. Modell-Schlüssel; Hersteller-Guard über ps.manufacturer
    SELECT
        v.*,
        insights.printer_model_key(v.printer_model) AS ps_key
    FROM insights.vw_printer_supplies v
),
-- Plattformen, auf denen GENAU EIN abgedecktes Consumer-Modell liegt (eindeutig):
-- nur diese taugen als Brücke. Gezählt wird über die direkt auflösbaren Geräte.
plat_twin AS (
    SELECT d.platform, min(d.dev_key) AS twin_key
    FROM dev d
    WHERE d.platform IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM ps
          WHERE ps.printer_model = d.model_display
             OR (ps.ps_key = d.dev_key
                 AND d.manufacturer_canonical ILIKE ps.manufacturer || '%')
      )
    GROUP BY d.platform
    HAVING count(DISTINCT d.dev_key) = 1
)
SELECT DISTINCT ON (d.fleetmgmt_device_id, ps.part_number, ps.part_category)
    d.fleetmgmt_device_id,
    d.manufacturer_serial,
    d.radix_device_number,
    d.model_display,
    d.manufacturer_canonical,
    d.device_status,
    CASE
        WHEN ps.printer_model = d.model_display THEN 'exact'
        WHEN ps.ps_key = d.dev_key             THEN 'model_key'
        ELSE 'platform'
    END                          AS match_method,
    ps.manufacturer              AS supply_manufacturer,
    ps.printer_model             AS matched_printer_model,
    d.platform                   AS lexmark_platform,
    ps.part_category,
    ps.part_number,
    ps.nominal_lifetime_pages,
    ps.color_channel,
    ps.supply_color,
    ps.yield_variant,
    ps.iso_standard,
    ps.source_url,
    ps.lifetime_source
FROM dev d
LEFT JOIN plat_twin pt ON pt.platform = d.platform
JOIN ps
    ON d.manufacturer_canonical ILIKE ps.manufacturer || '%'
   AND (
        ps.printer_model = d.model_display                                   -- exact
     OR ps.ps_key = d.dev_key                                               -- model_key
     OR (d.dev_key IS DISTINCT FROM pt.twin_key AND ps.ps_key = pt.twin_key) -- platform
   )
ORDER BY d.fleetmgmt_device_id, ps.part_number, ps.part_category,
         CASE
             WHEN ps.printer_model = d.model_display THEN 1
             WHEN ps.ps_key = d.dev_key             THEN 2
             ELSE 3
         END;
