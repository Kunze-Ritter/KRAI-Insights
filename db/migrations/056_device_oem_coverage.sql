-- 056_device_oem_coverage.sql
-- Vereinheitlichte OEM-Verbrauchsmaterial-Abdeckung je Gerät über BEIDE Daten-Pfade.
--
-- Loch (Systemüberblick 2026-05-26): Die geräte-genaue Toner-Sicht vw_device_supplies
-- speist sich nur aus dem Crawler (part_compatibility: Lexmark/HP/Kyocera). Konica
-- Minolta hat KEINE per-Drucker-Kompatibilität (die KM-Reichweiten kommen pro
-- Hersteller×Teiltyp aus der Excel-Liste in part_lifetime_oem). Dadurch erschien KM
-- (1.167 Live-Geräte, 2.-größter Bestand) in der Abdeckungs-Kennzahl fälschlich als
-- 0 % — obwohl voll abgedeckt, nur über den anderen Pfad.
--
-- Diese View liefert pro Gerät eine EHRLICHE Abdeckungs-Aussage über beide Pfade:
--   oem_quelle = 'crawler'   -> per-Drucker-Supplies vorhanden (vw_device_supplies)
--                'oem_liste' -> OEM-Reichweiten für den Hersteller vorhanden (KM-Excel)
--                NULL        -> keine OEM-Daten (Samsung/Canon/… ohne Quelle)
-- hat_oem_daten = (crawler ODER oem_liste).

-- Leichtgewichtig auf HERSTELLER-Ebene: ein Gerät gilt als OEM-abgedeckt, wenn für
-- seinen Hersteller OEM-Reichweiten in part_lifetime_oem vorliegen — egal über welchen
-- Pfad (Crawler: vbm_crawler% / KM-Excel: km_excel%). Das ist die EHRLICHE
-- vereinheitlichte Abdeckung und vermeidet die teure per-Gerät-Auswertung der schweren
-- View vw_device_supplies (die ein korreliertes EXISTS minutenlang laufen ließ).
-- Hinweis: pro-Drucker-genaue Lücken (welches EINZELNE Modell ohne Supply) bleiben in
-- vw_device_supplies sichtbar; diese View ist die Abdeckungs-Kennzahl.
CREATE OR REPLACE VIEW insights.vw_device_oem_coverage AS
WITH mfr_oem AS (
    SELECT manufacturer,
           CASE WHEN bool_or(source LIKE 'vbm_crawler%') THEN 'crawler' ELSE 'oem_liste' END AS quelle
    FROM insights.part_lifetime_oem
    GROUP BY manufacturer
)
SELECT
    d.fleetmgmt_device_id,
    d.manufacturer_canonical,
    d.model_display,
    d.device_status,
    mo.quelle                  AS oem_quelle,
    (mo.manufacturer IS NOT NULL) AS hat_oem_daten
FROM insights.devices_unified d
LEFT JOIN mfr_oem mo ON mo.manufacturer ILIKE d.manufacturer_canonical || '%';
