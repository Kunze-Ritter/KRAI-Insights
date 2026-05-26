-- 051_device_supplies_normalized.sql
-- Verbindet die Fleet-Geräte (devices_unified) mit den OEM-Verbrauchsmaterialien
-- aus dem VBM-Crawler (vw_printer_supplies / part_compatibility) — robust gegen die
-- "verschmutzten" Lexmark-Modellnamen und gegen Lexmarks Vertrags-Umlabelungen.
--
-- PROBLEM:
--   FleetMgmt liefert das Modell als FREITEXT, der bei Lexmark Seriennummer +
--   Plattform-Code enthält, z. B.
--       "Lexmark CX735adse 7530529514VH9 CXTMM.250.217"
--   Ein exakter Vergleich model_display = printer_model trifft daher 0 Lexmark-Geräte
--   (gegenüber HP 99,9 %, wo model_display sauber ist). Zusätzlich verkauft Lexmark
--   dieselbe Hardware unter Vertrags-/Enterprise-Namen (XC/XM/M/C-Serie), die der
--   Crawler gar nicht kennt — die Website listet nur die Consumer-Namen (CX/MX/CS/MS).
--
-- LÖSUNG — drei Match-Ebenen (match_method), von sicher nach hergeleitet:
--   1) 'exact'     : model_display == printer_model (trägt HP unverändert).
--   2) 'model_key' : normalisierter Modell-Schlüssel [a-z]{1,3}[0-9]{2,6}
--                    ("cx735" aus dem Freitext) == derselbe Schlüssel des Crawler-
--                    Druckers. Schält Seriennummer/Plattform-Suffix ab → löst die
--                    Lexmark-Verschmutzung (0 % → ~60 %).
--   3) 'platform'  : Lexmarks EIGENER Firmware-Plattform-Code (4.+5.-stelliges
--                    Suffix "CXTMM.250.217" → "CXTMM"). Geräte derselben Plattform
--                    teilen sich die Verbrauchsmaterialien (Toner-Familie). Wenn auf
--                    einer Plattform genau EIN abgedecktes Consumer-Modell liegt
--                    (eindeutig), erbt das Vertrags-Modell dessen Supplies
--                    (z. B. XC4352/XC4342 → CX735 auf Plattform CXTMM). ~60 % → ~88 %.
--                    Die Eindeutigkeits-Bedingung (genau 1 abgedeckter Schlüssel je
--                    Plattform) verhindert Fehlzuordnung bei Misch-Plattformen.
--
-- Der Plattform-Code ist Lexmark-spezifisch (Strukturmuster LETTERS.NNN.NNN); HP &
-- andere liefern ihn nicht → 'platform' feuert dort nie, HP bleibt rein 'exact'.
-- KM läuft NICHT über part_compatibility (Excel-Quelle) und ist hier bewusst leer.
--
-- Verbleibende Lücke (~12 % Lexmark): Vertrags-Modelle auf Plattformen OHNE
-- abgedecktes Consumer-Pendant in unserer Flotte (z. B. C4342/C4352, M3250, XM3142).
-- Die brauchen Crawler-Daten, die der Crawler noch nicht hat — siehe docs.

-- 1) Normalisierter Modell-Schlüssel ---------------------------------------------
-- Erste Folge "1-3 Buchstaben + 2-6 Ziffern" (case-insensitiv) aus einem Freitext.
-- "Lexmark CX735adse 753..." -> "cx735";  "HP LaserJet MFP E62665" -> "e62665".
-- NULL für ziffern-erste Modelle (z. B. HP 4102) — die laufen weiter rein über 'exact'.
CREATE OR REPLACE FUNCTION insights.printer_model_key(p text)
RETURNS text LANGUAGE sql IMMUTABLE AS $fn$
    SELECT (regexp_match(lower(coalesce(p, '')), '[a-z]{1,3}[0-9]{2,6}'))[1]
$fn$;

-- 2) Lexmark Firmware-Plattform-Code ---------------------------------------------
-- Suffix-Muster "CXTMM.250.217" -> "CXTMM" (4-6 Großbuchstaben, dann .NNN.NNN).
-- NULL, wenn das Muster fehlt (alle Nicht-Lexmark-Modelle).
CREATE OR REPLACE FUNCTION insights.printer_platform_code(p text)
RETURNS text LANGUAGE sql IMMUTABLE AS $fn$
    SELECT (regexp_match(coalesce(p, ''), '([A-Z]{4,6})\.[0-9]{3}\.[0-9]{3}'))[1]
$fn$;

-- 3) Geräte -> passende OEM-Verbrauchsmaterialien --------------------------------
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
ps AS (  -- Crawler-Supplies inkl. Modell-Schlüssel + Marke des Druckernamens
    SELECT
        v.*,
        insights.printer_model_key(v.printer_model) AS ps_key,
        split_part(v.printer_model, ' ', 1)         AS ps_brand
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
                 AND d.manufacturer_canonical ILIKE ps.ps_brand || '%')
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
    ON d.manufacturer_canonical ILIKE ps.ps_brand || '%'
   AND (
        ps.printer_model = d.model_display                                   -- exact
     OR ps.ps_key = d.dev_key                                               -- model_key
     OR (d.dev_key IS DISTINCT FROM pt.twin_key AND ps.ps_key = pt.twin_key) -- platform
   )
-- DISTINCT ON behält pro (Gerät, Teilenummer) das sicherste Verfahren:
ORDER BY d.fleetmgmt_device_id, ps.part_number, ps.part_category,
         CASE
             WHEN ps.printer_model = d.model_display THEN 1
             WHEN ps.ps_key = d.dev_key             THEN 2
             ELSE 3
         END;
