# Observability — Daten-Aktualität & ETL-Läufe

Die Auswertungs-Datenbank ist ein **abgeleiteter Cache**, der nächtlich aus den drei
Quellen neu aufgebaut wird (FleetMgmt, Radix, KRAI — alle nur lesend). Das Risiko dabei:
Wenn ein nächtlicher Lauf fehlschlägt, sind die Zahlen im Dashboard **veraltet, ohne dass
es jemand merkt** — und veraltete Daten sehen aus wie frische. Für ein Werkzeug, das
Garantie- und Geld-Entscheidungen stützt, ist das das Hauptrisiko.

Migration `064_observability.sql` macht beides sichtbar: **lief der Nightly durch?** und
**wie alt sind die Daten je Tabelle?**

## 1. Lauf-Protokoll (`scheduler_runs`)

Der Scheduler (`insights/etl/scheduler.py`) schreibt für **jeden Schritt** eine Zeile:
Start, Ende, Status (`running` / `ok` / `failed`), Ergebnis des Loaders (Counts) und bei
Fehlern den Fehlertext. Alle Schritte eines Laufs teilen eine `run_id`.

- Ein Schritt, der **hängt** (z. B. ein Radix-Crawl ohne Antwort), wird nach
  `SCHED_STEP_TIMEOUT_SEC` (Standard 3600 s = 1 h) als `failed` mit `error='timeout'`
  abgebrochen — ein einzelner Hänger blockiert nicht die ganze Nacht.
- Bleibt eine Zeile auf `running` stehen, wurde der Prozess **mitten im Schritt** beendet
  (Crash/Kill) — ein klares Signal.

## 2. Daten-Frische je Tabelle (`vw_table_freshness`)

Je Kerntabelle der letzte Daten-Stand (`max(ingested_at)` bzw. `updated_at`), die
erwartete Kadenz und ein abgeleiteter Status:

| Status | Bedeutung |
|---|---|
| **frisch** | Stand jünger als die Schwelle |
| **veraltet** | älter als die Schwelle → Nightly vermutlich ausgefallen |
| **leer** | Tabelle nie geladen |

Schwellen: **daily-Tabellen 36 h** (ein ausgefallener nächtlicher Lauf fällt sofort auf),
**weekly-Tabellen 192 h (8 Tage)**. Überwacht werden: `devices_unified`,
`vbm_lifecycle_events`, `snmp_predictions`, `error_code_ref`, `model_toner_oem` (daily)
sowie `cost_events`, `device_contracts` (weekly).

## 3. Letzter Lauf je Pipeline (`vw_etl_status`)

Fasst den jeweils jüngsten Lauf je Pipeline zusammen: wann gestartet/beendet, wie viele
Schritte ok/fehlgeschlagen/laufend, und die Namen der fehlgeschlagenen Schritte.

## 4. Im Dashboard

- **Roter Banner** (oben, auf jeder Seite) — erscheint **nur**, wenn eine Tabelle
  veraltet/leer ist ODER der letzte Lauf fehlgeschlagene Schritte hatte. Sonst still.
- **Übersicht → „Datenquellen & Stand"** zeigt den jüngsten Daten-Stand und die
  Detail-Tabellen (`insights/ui/freshness.py`).

## 5. Alarmierung (optional)

Ist die Umgebungsvariable `SCHED_ALERT_WEBHOOK` gesetzt, sendet eine Pipeline mit
mindestens einem fehlgeschlagenen Schritt am Ende einen JSON-POST dorthin (Slack-/Teams-/
n8n-kompatibles `{text, pipeline, run_id, failed_steps}`). Ohne Webhook: nur DB + Log.

## 6. Nachschauen (SQL)

```sql
-- Aktualität auf einen Blick
SELECT * FROM insights.vw_table_freshness ORDER BY status, tabelle;

-- letzter Lauf je Pipeline
SELECT * FROM insights.vw_etl_status;

-- die letzten 20 Schritte
SELECT pipeline, step, status, started_at, finished_at, error
FROM insights.scheduler_runs ORDER BY started_at DESC LIMIT 20;
```
