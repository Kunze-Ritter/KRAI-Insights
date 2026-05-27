-- 063_km_oem_self_target_bridge.sql
-- KM-Bruecke fuer die Garantie/Yield-Bewertung — schliesst die in Migration 062 bewusst
-- offen gelassene Konica-Minolta-Luecke (~3.000 unbewertete Tonerwechsel).
--
-- Befund: KM hat KEINE per-Modell-Kompatibilitaet im Crawler (Excel-Pfad), und die
-- vorhandenen km_excel-Tonerzahlen waren teils synthetisch (alle TN-514, EAGLE/FALCON/
-- ZEUS mit glatt absteigenden Werten — fuer C458 sogar falsch: 56k statt real 28k).
-- ABER: FleetMgmt selbst meldet je Event einen oem_target_pages — nur LUECKENHAFT. Fuer
-- dasselbe Modell x Farbe haben viele Events den Wert (z. B. bizhub C450i schwarz = 28.000
-- ueber 1.181 Events, 100 % konsistent), andere nicht. Der von FleetMgmt gemeldete Wert ist
-- zudem KORREKT (C458=28k deckt sich mit TN-514K real), schlaegt also den Excel-Seed.
--
-- Loesung: den OEM-Soll je Modell x Farbe aus KMs EIGENEN konsistent gemeldeten Werten
-- ableiten (Median ueber die Geschwister-Events; min/max -> Spread -> Konfidenz wie in 062)
-- und in model_toner_oem einspeisen. Die 062-Fallback-Logik in vw_vbm_lifecycle greift dann
-- automatisch (LEFT JOIN model_toner_oem auf model_display + Farbe). KEINE View-Aenderung.
--
-- Der Ansatz ist herstelleragnostisch (hilft jedem Modell mit gespeicherten, aber spaerlichen
-- Soll-Werten); ON CONFLICT DO NOTHING laesst die Crawler-Zeilen (HP/Lexmark/Kyocera)
-- unangetastet — der Selbst-Soll fuellt nur Modelle OHNE Crawler-Abdeckung (v. a. KM).
-- Voll rebuildbar: refresh_model_toner_oem() baut Crawler- UND Selbst-Soll-Zeilen neu auf.

-- 1) Quelle der model_toner_oem-Zeilen kennzeichnen (Crawler vs. Selbst-Soll).
ALTER TABLE insights.model_toner_oem
    ADD COLUMN IF NOT EXISTS source varchar(20) NOT NULL DEFAULT 'device_supplies';

-- 2) Selbst-Soll je Modell x Farbe aus den FleetMgmt-gemeldeten OEM-Zielen ableiten.
--    Median = robuster Soll (ignoriert seltene Ausreisser wie 600.000); min/max -> Spread
--    -> Konfidenz. Nur Gruppen mit >=5 belegten Events (Stabilitaet). Crawler-Zeilen
--    behalten Vorrang (ON CONFLICT DO NOTHING).
INSERT INTO insights.model_toner_oem
    (model_display, color_channel, oem_min, oem_median, oem_max, sku_count, is_mono_model, source)
SELECT d.model_display,
       CASE lower(btrim(ev.colorant))
            WHEN 'black' THEN 'bw' WHEN 'cyan' THEN 'c'
            WHEN 'magenta' THEN 'm' WHEN 'yellow' THEN 'y' END AS chan,
       min(ev.oem_target_pages)::int,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY ev.oem_target_pages))::int,
       max(ev.oem_target_pages)::int,
       count(*)::int,
       NULL::boolean,
       'self_target'
FROM insights.vbm_lifecycle_events ev
JOIN insights.devices_unified d ON d.fleetmgmt_device_id = ev.fleetmgmt_device_id
WHERE ev.oem_target_pages > 0
  AND lower(btrim(ev.colorant)) IN ('black', 'cyan', 'magenta', 'yellow')
  AND d.model_display IS NOT NULL
GROUP BY d.model_display, chan
HAVING count(*) >= 5
ON CONFLICT (model_display, color_channel) DO NOTHING;
