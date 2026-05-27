-- 059_fremdgeraete_radar.sql
-- "Spionage" / Wettbewerbs-Radar: Wird der DCA/CSP-Agent auf einem Kundenserver nach
-- Vertragsende nicht deinstalliert, melden sich dort weiterhin ALLE Geräte automatisch
-- in die Flotten-Verwaltung — auch die NEUEN (Konkurrenz-)Geräte, die der Kunde
-- aufstellt. Wir sehen sie also, obwohl wir sie nicht servicieren.
--
-- Signal: device_status='live' (meldet aktuell Daten) UND radix_device_number IS NULL
-- (kein KR-Service-/Vertrags-Link in Radix) → Fremdgerät, über den Agent sichtbar.
--
-- Einordnung je Kunde:
--   'verlorener_kunde_agent_aktiv'   – beim Kunden KEINE KR-servicierten Live-Geräte
--                                      mehr, aber Fremdgeräte melden → Kunde verloren,
--                                      Agent läuft noch (volle Sicht auf neue Fremdflotte;
--                                      Win-Back-Chance ODER Agent deinstallieren).
--   'fremdgeraet_bei_aktivem_kunden' – Kunde hat noch KR-Geräte, daneben Fremdgeräte
--                                      (Up-Sell / Beobachtung, ggf. Konkurrenz im Haus).
-- 'neu_aufgetaucht' = deployed in den letzten 365 Tagen (frisch dazugestellt).

-- DROP + CREATE (statt CREATE OR REPLACE): die Spalte konkurrenzmarke wird in der
-- Mitte eingefügt, das erlaubt CREATE OR REPLACE nicht. View ist neu, keine Abhängigkeiten.
DROP VIEW IF EXISTS insights.vw_fremdgeraete;
CREATE VIEW insights.vw_fremdgeraete AS
WITH kr_per_kunde AS (   -- KR-servicierte (in Radix) Live-Geräte je Kunde
    SELECT customer_name, count(*) AS kr_live
    FROM insights.devices_unified
    WHERE device_status = 'live' AND radix_device_number IS NOT NULL
    GROUP BY customer_name
)
SELECT
    d.customer_name,
    d.customer_city,
    d.manufacturer_canonical,
    d.model_display,
    d.manufacturer_serial AS device_serial,
    d.hostname,
    d.printer_ip,
    d.deployed_date,
    d.last_data_transfer_at::date AS letzte_meldung,
    (d.deployed_date > now() - interval '365 days') AS neu_aufgetaucht,
    -- Marke ist KEINE KR-Kernmarke (KM/Lexmark/HP/Kyocera) → Konkurrenz-Verdacht
    (d.manufacturer_canonical IS NOT NULL
     AND d.manufacturer_canonical NOT IN ('Konica Minolta', 'Lexmark', 'HP', 'Kyocera')) AS konkurrenzmarke,
    COALESCE(k.kr_live, 0) AS kr_geraete_beim_kunden,
    CASE WHEN COALESCE(k.kr_live, 0) = 0
         THEN 'verlorener_kunde_agent_aktiv'
         ELSE 'fremdgeraet_bei_aktivem_kunden' END AS einordnung
FROM insights.devices_unified d
LEFT JOIN kr_per_kunde k ON k.customer_name = d.customer_name
WHERE d.device_status = 'live'              -- meldet aktuell (über den Agent sichtbar)
  AND d.radix_device_number IS NULL         -- aber kein KR-Service-Link in Radix
  AND NOT COALESCE(d.unmanaged, false);     -- bereits unmanaged gesetzte ignorieren
