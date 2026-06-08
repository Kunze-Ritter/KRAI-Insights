-- 065_data_quality.sql
-- Datenqualitaets-Kennzahlen in einer View buendeln (Backing fuer den DQ-Tab).
--
-- Hintergrund: Ein systematisches Audit (2026-06-08) hat den Ist-Zustand geprueft.
-- Befund: Die Daten sind gut (OEM-Abdeckung 97 %, Identitaet/Datums-Sanity sauber).
-- Die scheinbar niedrige Garantie-„Bewertbarkeit" ist KEIN Datenloch: 121k der VBM-
-- Events sind Status-Mehrfachmeldungen (<7 Tage Abstand) bzw. Erstkartuschen — die
-- echte Kartuschen-Reichweite (~12,7k Seiten Median) steckt korrekt im Wechsel-Event.
-- Die heutige `pages_since_previous`-Methodik ist also RICHTIG; bewusst keine Aenderung.
-- (Details: docs/datenqualitaet.md §11.)
--
-- Diese View macht die Audit-Kennzahlen laufend sichtbar (DQ-Tab). Tall-Format
-- (eine Zeile je Kennzahl), damit der UI sie als Tabelle + Ampel zeigen kann.
-- Jede Subquery ist unabhaengig + leichtgewichtig (Counts ueber 12k–200k Zeilen).

CREATE OR REPLACE VIEW insights.vw_data_quality AS
WITH rows AS (
  SELECT 10 AS sort, 'Identität' AS kategorie, 'Geräte gesamt' AS kennzahl,
         (SELECT count(*) FROM insights.devices_unified)::numeric AS wert,
         'gut'::text AS bewertung, ''::text AS hinweis
  UNION ALL SELECT 20, 'Identität', 'ohne Hersteller-Serial',
         (SELECT count(*) FROM insights.devices_unified WHERE manufacturer_serial IS NULL OR manufacturer_serial = ''),
         'info', 'enthält Queue-Artefakte + FleetMgmt-only-Geräte'
  UNION ALL SELECT 30, 'Identität', 'ohne Radix-Verknüpfung',
         (SELECT count(*) FROM insights.devices_unified WHERE radix_device_number IS NULL),
         'info', 'überwiegend nicht-live (still/gelöscht); nur die live-Geräte sind relevant'
  UNION ALL SELECT 40, 'Identität', 'ohne kanonisches Modell',
         (SELECT count(*) FROM insights.devices_unified WHERE model_id IS NULL),
         'info', 'Modell nicht im KRAI-Katalog auflösbar'
  UNION ALL SELECT 50, 'Identität', 'Queue-Artefakte (Phantom-Geräte)',
         (SELECT count(*) FROM insights.devices_unified WHERE is_queue_artifact),
         'info', 'Print-Server-Queues, kein echtes Gerät (aus live herausgerechnet)'
  -- Geräte-Status
  UNION ALL SELECT 110, 'Status', 'live (meldet, echt)',
         (SELECT count(*) FROM insights.devices_unified WHERE device_status = 'live' AND NOT COALESCE(is_queue_artifact, false)),
         'gut', 'Datenübertragung < 60 Tage'
  UNION ALL SELECT 120, 'Status', 'silent (kein aktueller Zähler)',
         (SELECT count(*) FROM insights.devices_unified WHERE device_status = 'silent'),
         'info', 'Abrechnung läuft ggf. auf Schätzwerten — siehe Abrechnungs-Risiko'
  -- Abdeckung
  UNION ALL SELECT 210, 'Abdeckung', 'OEM-Toner-Abdeckung live (%)',
         (SELECT round(100.0 * count(*) FILTER (WHERE hat_oem_daten) / NULLIF(count(*), 0), 1)
          FROM insights.vw_device_oem_coverage WHERE device_status = 'live'),
         'gut', 'Anteil live-Geräte mit hinterlegtem OEM-Toner-Soll'
  UNION ALL SELECT 220, 'Abdeckung', 'Material-Kostenzeilen mit Preis (%)',
         (SELECT round(100.0 * count(*) FILTER (WHERE unit_price > 0) / NULLIF(count(*), 0), 1)
          FROM insights.cost_events WHERE cost_type = 'material'),
         'schwach', 'Radix erfasst Preise oft nicht — Kosten/Profitabilität auf dünner Basis'
  -- Garantie (korrekt eingeordnet)
  UNION ALL SELECT 310, 'Garantie', 'belastbare Garantiefälle (claim, hoch/mittel)',
         (SELECT count(*) FROM insights.vw_warranty_assessment
          WHERE warranty_class = 'claim' AND oem_konfidenz IN ('hoch', 'mittel')),
         'gut', 'Methodik validiert (pages_since_previous am Wechsel-Event, ~12,7k Seiten Median)'
  -- Korrektur-Kandidaten
  UNION ALL SELECT 410, 'Korrektur', 'Kundenzuordnung abweichend (FleetMgmt↔Radix)',
         (SELECT count(*) FROM insights.vw_customer_device_mismatch WHERE abgleich = 'abweichung'),
         'mittel', 'Toner-Fehlversand-/Abrechnungsrisiko — manuell prüfen'
  UNION ALL SELECT 420, 'Korrektur', 'Geräte mit doppelter Seriennummer',
         (SELECT COALESCE(sum(n), 0) FROM (SELECT count(*) n FROM insights.devices_unified
            WHERE manufacturer_serial <> '' GROUP BY manufacturer_serial HAVING count(*) > 1) x),
         'mittel', 'überwiegend verkaufte/verschobene Geräte — siehe match_review_queue'
  UNION ALL SELECT 430, 'Korrektur', 'live-Geräte ohne Radix (Matching-Reserve)',
         (SELECT count(*) FROM insights.devices_unified
          WHERE radix_device_number IS NULL AND device_status = 'live' AND NOT COALESCE(is_queue_artifact, false)),
         'mittel', 'kleine Restmenge zum manuellen Zuordnen'
  UNION ALL SELECT 440, 'Korrektur', 'VBM negative Seiten-Deltas (Rauschen)',
         (SELECT count(*) FROM insights.vbm_lifecycle_events WHERE pages_since_previous < 0),
         'info', 'Counter-Reset/Geräte-Tausch — wird in der Bewertung nicht mitgezählt'
)
SELECT kategorie, kennzahl, wert, bewertung, hinweis, sort, 'insights'::text AS source_system
FROM rows ORDER BY sort;
