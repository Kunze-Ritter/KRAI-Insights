-- 060_fremdgeraete_identity_filter.sql
-- Bereinigt vw_fremdgeraete um IDENTITÄTSLOSE Einträge: Manche Kunden (z. B.
-- BruderhausDiakonie, 82 Stück) haben einen Windows-Print-Server, dessen Druck-
-- Warteschlangen/Ports der DCA als "Geräte" mitzählt — IPAddress = "PS30xxx", aber
-- KEINE Seriennummer, KEIN Modell, KEIN Hersteller, KEIN MAC. Das sind keine
-- physischen (Konkurrenz-)Kopierer, sondern Spooler-Artefakte und verfälschen den
-- Wettbewerbs-Radar.
--
-- Fix: nur Einträge mit MINDESTENS einer Geräte-Identität (Hersteller ODER
-- Seriennummer ODER Modell) zeigen. Effekt: 173 → 75 echte Fremdgeräte; die
-- Konkurrenzmarken-Intel (23) bleibt unverändert. Spalten unverändert → CREATE OR REPLACE.
--
-- (Die PS-Queue-Einträge tragen weiterhin Zählerstände und bleiben in der Flotte
-- erhalten — sie werden nur aus dem identitätsabhängigen Fremdgeräte-Radar gefiltert.)

CREATE OR REPLACE VIEW insights.vw_fremdgeraete AS
WITH kr_per_kunde AS (
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
    (d.manufacturer_canonical IS NOT NULL
     AND d.manufacturer_canonical NOT IN ('Konica Minolta', 'Lexmark', 'HP', 'Kyocera')) AS konkurrenzmarke,
    COALESCE(k.kr_live, 0) AS kr_geraete_beim_kunden,
    CASE WHEN COALESCE(k.kr_live, 0) = 0
         THEN 'verlorener_kunde_agent_aktiv'
         ELSE 'fremdgeraet_bei_aktivem_kunden' END AS einordnung
FROM insights.devices_unified d
LEFT JOIN kr_per_kunde k ON k.customer_name = d.customer_name
WHERE d.device_status = 'live'
  AND d.radix_device_number IS NULL
  AND NOT COALESCE(d.unmanaged, false)
  -- nur Einträge mit echter Geräte-Identität (filtert Print-Server-Queues "PS30xxx" raus)
  AND (d.manufacturer_canonical IS NOT NULL
       OR d.manufacturer_serial IS NOT NULL
       OR d.model_display IS NOT NULL);
