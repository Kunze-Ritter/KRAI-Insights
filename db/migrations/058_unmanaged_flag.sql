-- 058_unmanaged_flag.sql
-- CSP/FleetMgmt kennt für jedes Gerät ein "Unmanaged"-Flag (ACCDEVICES.Unmanaged) —
-- damit setzt man auto-aufgenommene Geräte aus der Verwaltung/Lizenz heraus, ohne sie
-- zu löschen. Das gehört in die Lizenz-Verschwendungs-Liste berücksichtigt: ein
-- bereits "unmanaged" gesetztes Gerät kostet keine Lizenz mehr → darf NICHT als
-- Delisting-Kandidat erscheinen.
--
-- Befund (2026-05-27): aktuell ist Unmanaged kaum genutzt (101 Geräte, alle bereits
-- gelöscht/deaktiviert; 0 unmanaged-aber-aktiv). Das operative "Inaktiv" = das
-- Deactivated-Flag (nur 34 von 5.419 real inaktiven). Diese Spalte macht die Liste
-- ZUKUNFTSSICHER: sobald KR Geräte unmanaged setzt, fallen sie automatisch raus.
--
-- 1) Spalte ergänzen (NULLable; wird vom FleetMgmt-Loader befüllt).
ALTER TABLE insights.devices_unified
    ADD COLUMN IF NOT EXISTS unmanaged boolean;

-- 2) vw_lizenz_verschwendung neu: schließt unmanaged-Geräte aus + zeigt das Flag.
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
WHERE d.device_status NOT IN ('deleted', 'deactivated')   -- noch CSP-lizenziert (= Status-Flag)
  AND NOT COALESCE(d.unmanaged, false)                    -- und NICHT bereits unmanaged gesetzt
  AND d.device_status <> 'live';                          -- aber nicht aktiv = Verschwendungs-Verdacht
