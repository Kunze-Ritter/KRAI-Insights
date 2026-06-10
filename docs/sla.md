# SLA & Reaktionszeiten — Dokumentation

## Was ist ein SLA?

Ein **Service Level Agreement (SLA)** ist eine interne Vereinbarung, innerhalb welcher Zeit KR auf Serviceaufträge reagiert und das Gerät wiederherstellt. Die SLA-Ziele gelten nur für **technische Störungen** (Gerät nicht funktionsfähig oder eingeschränkt) — Wartung und Installation haben keine SLA-Pflicht.

## SLA-Klassen

| Klasse | Bezeichnung | Ziel |
|--------|-------------|------|
| **A** | Störung A — Blockierend | Wiederherstellung innerhalb **8 Stunden** nach Auftragseingang |
| **B** | Störung B — Nicht blockierend | Wiederherstellung bis zum **nächsten Arbeitstag (NBD)** |
| **C** | Wartung / Installation / Support | Kein SLA-Ziel |

SLAs gelten nur während der Geschäftszeiten **Mo–Fr 07:30–17:30 Uhr**.

## Datenquelle

- **Ticket-Erstellzeit:** `documentDate` aus dem Radix-Ticket-Endpoint (`/api/ticket`)  
  → wird per `--radix-tickets`-ETL in `insights.radix_tickets` geladen
- **Abschlusszeit:** letzte Aktivität in `insights.activity_notes` (`activity_datetime` wenn vorhanden, sonst `activity_date`)
- **Ticket-Kategorie:** Radix `maintenanceType`, z.B. `"010/040/010 - Blockierend"`

## Klassifizierungslogik (in `vw_sla_tickets`)

```sql
-- Priorität aus maintenanceType:
WHEN maintenance_type ILIKE '%040/010%' THEN 'A'  -- Blockierend
WHEN priority_type = 'High'            THEN 'A'  -- manuell als dringend markiert
WHEN maintenance_type ILIKE '%/040/%'  THEN 'B'  -- Blockierend/Nicht blockierend
WHEN maintenance_type ILIKE '%/020/%'
  OR maintenance_type ILIKE '%/030/%'
  OR maintenance_type ILIKE '%/070/%'  THEN 'B'  -- Druck, Papier, Qualität
ELSE 'C'                                           -- Wartung, Installation, Support

-- Kategorie:
WHEN '%/040/%' OR '%/020/%' OR '%/030/%' OR '%/070/%' → 'Störung'
WHEN '%/010/%'                                        → 'Wartung'
WHEN '%/080/%'                                        → 'Installation'
WHEN '%/090/%'                                        → 'Support'
```

## Genauigkeit der Zeitberechnung

Die Abschlusszeit wird aus dem letzten Activity-Datum abgeleitet:

| Verfügbarkeit | Genauigkeit | Quelle |
|---|---|---|
| `activity_datetime` gesetzt (neue Crawls) | Stunden | `activity_notes.activity_datetime` |
| Nur `activity_date` vorhanden (Alt-Daten) | Tag (±17:00 Uhr Fallback) | `activity_notes.activity_date` |

**SLA A (8h):** Bei Tag-Genauigkeit gilt: Ticket am selben Tag eröffnet und abgeschlossen → gilt als „eingehalten" (konservative Näherung). Für stundengenaue Auswertung: `--tickets`-Crawl wiederholen, damit `activity_datetime` befüllt wird.

**SLA B (NBD):** `closed_date - created_date ≤ 1 Tag` → gilt als eingehalten. Das ist zuverlässig.

## ETL & Aktualisierung

```bash
# Einmalig (nach Migration 072): alle Tickets laden
docker exec krai-insights-app python -m insights.etl.load --radix-tickets

# Im Nightly (scheduler.py daily_refresh) automatisch
# HINWEIS: radix_tickets ist noch NICHT im Nightly eingebunden — manuell ergänzen wenn gewünscht
```

Crawl-Dauer: ca. 5–15 Minuten je nach Anzahl Kunden (paginiert mit 10er Concurrency).

## Bekannte Lücken

- **Geschäftsstunden** werden nicht herausgerechnet — ein Ticket am Freitag um 17:00 Uhr, das Montag um 08:00 erledigt wird, erscheint als „NBD nicht eingehalten", obwohl es korrekt wäre.
- **KM-Ticket-Codes** (`TIC-A-` Format) hatten früher die Priorität im Code — diese werden ebenfalls korrekt erkannt.
- **Offene Tickets** (state ≠ ERL) werden im Volume-Chart mitgezählt, aber nicht in der SLA-Quote (da noch kein Abschlussdatum).
- **Tickets ohne Aktivitäten** in `activity_notes` haben keine Abschlusszeit → erscheinen nicht in der SLA-Quote.

## Hintergrund (aus internem Report 2018)

Im internen KR-Report 2018 wurden folgende Zielwerte dokumentiert:
- SLA A: 71,43 % Einhaltungsquote
- SLA B: 80,84 % Einhaltungsquote

Diese Werte können als historische Benchmark für die aktuelle Entwicklung herangezogen werden.
