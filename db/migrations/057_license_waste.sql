-- 057_license_waste.sql
-- Lizenz-Verschwendung: CSP nimmt Geräte automatisch unter Lizenz (kostet pro Gerät),
-- auch solche, die der Kunde nur noch herumstehen hat — abgebaut, ersetzt, offline.
-- Diese View listet Geräte, die noch CSP-lizenziert sind (in FleetMgmt gezählt, also
-- NICHT deleted/deactivated), aber NICHT mehr aktiv melden → Delisting-Kandidaten.
--
-- "lizenziert" = device_status NOT IN ('deleted','deactivated')  (= ~11.815, deckt
-- sich mit dem Admin-„aktiv"-Flag). Verschwendungs-Verdacht = davon alles, was nicht
-- 'live' ist (silent/never_reported) — diese Geräte kosten Lizenz, liefern aber nichts.
--
-- Stufen (lizenz_risiko), nach Delisting-Sicherheit:
--   'hoch'    – fast sicher weg: nie gemeldet, ODER >365 Tage still UND nicht in Radix,
--               ODER ohne Modell/Hersteller (Phantom-Eintrag).
--   'mittel'  – wahrscheinlich weg: >180 Tage keine Daten.
--   'niedrig' – beobachten: 60–180 Tage still (kann temporär offline sein).
-- Zusätzlich je Zeile der Grund (still seit X / nicht in Radix / ohne Modell / kein
-- Vertrag) für die manuelle Prüfung vor dem Delisting in CSP.
--
-- HINWEIS: ein Gerät, das LIVE meldet, ist KEINE Lizenz-Verschwendung (es ist in
-- Benutzung) — auch ohne Radix/Vertrag (das ist Up-Sell, siehe vw_out_of_contract).

CREATE OR REPLACE VIEW insights.vw_lizenz_verschwendung AS
SELECT
    d.customer_name,
    d.customer_city,
    d.manufacturer_canonical,
    d.model_display,
    d.manufacturer_serial      AS device_serial,
    d.radix_device_number,
    d.device_status,
    d.last_data_transfer_at::date AS letzte_meldung,
    (CURRENT_DATE - d.last_data_transfer_at::date) AS tage_inaktiv,
    (d.radix_device_number IS NOT NULL) AS in_radix,
    COALESCE(d.contract_active, false)  AS aktiver_vertrag,
    CASE
        WHEN d.device_status = 'never_reported'
             OR (d.device_status = 'silent' AND d.last_data_transfer_at < now() - interval '365 days'
                 AND d.radix_device_number IS NULL)
             OR d.manufacturer_canonical IS NULL
            THEN 'hoch'
        WHEN d.last_data_transfer_at < now() - interval '180 days' THEN 'mittel'
        ELSE 'niedrig'
    END AS lizenz_risiko,
    NULLIF(trim(BOTH ' ,' FROM concat_ws(', ',
        CASE WHEN d.device_status = 'never_reported' THEN 'nie gemeldet' END,
        CASE WHEN d.device_status = 'silent' AND d.last_data_transfer_at IS NOT NULL
             THEN 'still seit ' || (CURRENT_DATE - d.last_data_transfer_at::date) || ' Tagen' END,
        CASE WHEN d.radix_device_number IS NULL THEN 'nicht in Radix' END,
        CASE WHEN d.manufacturer_canonical IS NULL THEN 'ohne Modell/Hersteller' END,
        CASE WHEN COALESCE(d.contract_active, false) = false THEN 'kein aktiver Vertrag' END
    )), '') AS grund
FROM insights.devices_unified d
WHERE d.device_status NOT IN ('deleted', 'deactivated')   -- noch CSP-lizenziert
  AND d.device_status <> 'live';                          -- aber nicht aktiv = Verschwendungs-Verdacht
