# VBM-Crawler-Anbindung

KRAI-Insights bezieht Soll-Reichweiten (Page Yield, OEM-Soll) für
Verbrauchsmaterialien aus zwei Quellen:

| Quelle | Hersteller | Pipeline |
|---|---|---|
| **KM-Excel** (`krai_pm.part_lifetimes`) | Konica Minolta | `--partlifetimes` → `load_part_lifetimes()` |
| **VBM-Crawler** (`KRAI-Crawler-VBM/output/`) | Lexmark, später HP/Canon/KM | `--vbm-crawler` → `load_vbm_crawler()` |

Beide schreiben in dieselbe Tabelle `insights.part_lifetime_oem` — getrennt
über die `source`-Spalte (`km_excel_*` vs. `vbm_crawler:<vendor>_v*`). Migration
**047** trägt die natürliche UNIQUE-Constraint (nur für VBM-Crawler-Quellen),
fügt Spalten `supply_color` / `yield_variant` / `iso_standard` / `source_url`
hinzu und legt die zusätzliche m:n-Tabelle `insights.part_compatibility` an.

## Architektur

```
KRAI-Crawler-VBM/output/             ── Sibling-Repo, schreibt JSON
├── lexmark/supplies/*.json           (eine Datei pro Supply)
├── supplies-master.json              (konsolidiert)
├── alias-index.json
└── by-printer.json
            │  (read-only Mount /srv/vbm-crawler/ in den krai-insights-app Container)
            ▼
insights/etl/vbm_crawler_extractor.py ── liest supplies-master.json
            ▼
insights/etl/load.py::load_vbm_crawler() ── UPSERT
            ▼
insights.part_lifetime_oem        ── Soll-Reichweite (Toner, Drum, …)
insights.part_compatibility       ── m:n Supply ↔ Drucker
            ▼
insights.vw_printer_supplies      ── Komfort-View "welche Toner passen zu Drucker X"
+ vw_part_oem_comparison (037), vw_part_early_failures (045/038), … profitieren automatisch
```

## Setup (Docker)

`.env`:

```bash
VBM_CRAWLER_OUTPUT_HOST=C:\Github\KRAI-Crawler-VBM\output
VBM_CRAWLER_OUTPUT_DIR=/srv/vbm-crawler
```

`docker-compose.yml` mountet den Host-Pfad read-only nach `/srv/vbm-crawler/`
(siehe `app.volumes`). Beim Ändern der `.env` Container neu starten:

```powershell
docker compose up -d app
```

Migration anwenden (einmalig):

```powershell
docker exec krai-insights-app python scripts/migrate.py
```

Import laufen lassen:

```powershell
docker exec krai-insights-app python -m insights.etl.load --vbm-crawler
```

Idempotent — kann beliebig oft wiederholt werden (UPSERT auf `(manufacturer, part_number)`).

## Setup (Host / venv)

Wer den Insights-Stack lokal mit `.venv` startet:

```powershell
# .env leerlassen oder VBM_CRAWLER_OUTPUT_DIR auf den Host-Pfad zeigen
& .venv\Scripts\python.exe -m insights.etl.load --vbm-crawler
```

Default-Lookup: `../KRAI-Crawler-VBM/output/supplies-master.json` (Sibling-Layout).

## Schema-Mapping

Der Crawler liefert ein vendor-neutrales Schema (`vendor`, `supplyCode`,
`supplyType`, `color`, `yieldPages`, `compatiblePrinters[]`, …). Der Extractor
mappt darauf:

| Crawler-Feld | `part_lifetime_oem` |
|---|---|
| `vendorLabel` (z. B. "Lexmark") | `manufacturer` |
| `supplyType` (`toner`/`drum`/`developer`/…) | `part_category` |
| `supplyCode` (z. B. "79L2HK0") | `part_number` |
| `yieldPages` (Integer) | `nominal_lifetime_pages` |
| `color` → kurzgemappt (`black`→`bw`, `cyan`→`c`, …) | `color_channel` |
| `color` (Rohwert) | `supply_color` |
| `yieldVariant` | `yield_variant` |
| `isoStandard` (z. B. "ISO/IEC 19798") | `iso_standard` |
| `sourceUrl` | `source_url` |
| `"vbm_crawler:" + vendor + "_v0.1"` | `source` |

Pro Supply gibt es zusätzlich N Zeilen in `part_compatibility` (1 pro Eintrag
in `compatiblePrinters[]`). Im Lexmark-Vollcrawl (Mai 2026): 845 Lifetime-Zeilen
+ 5.990 Compatibility-Zeilen über 513 unique Drucker.

## Aktualisieren bei neuem Crawl

Wenn der VBM-Crawler neue Hersteller / neue Modelle gecrawlt hat:

1. Im Crawler-Repo: `npm run aggregate` (erzeugt frische `supplies-master.json`)
2. Im Insights-Repo: `docker exec krai-insights-app python -m insights.etl.load --vbm-crawler`

Da `output/supplies-master.json` per Volume in den Container gemountet ist,
sind Crawler-Änderungen automatisch sichtbar.

## Wirkung auf bestehende Views

`vw_part_oem_comparison`, `vw_part_early_failures`, `vw_spare_part_events`
(Migrationen 037/038/045) joinen über `manufacturer ILIKE '...%' + part_category`
auf `part_lifetime_oem`. Sobald für einen Hersteller dort Werte stehen, fließen
sie automatisch in:

- **OEM-Soll-vs-Ist-Vergleich** der Teile-Lebensdauer
- **Garantie-Frühausfälle** mit Konfidenz "hoch" (vorher: nur KM hatte das)
- **Toner-Yield-vs-OEM** (vw_toner_yield_vs_oem nutzt CoveragePagesTarget aus
  FleetMgmt direkt, aber unsere Lexmark-Soll-Werte sind eine unabhängige
  Cross-Check-Quelle)

## Quick-Check

```sql
-- Wieviele Reichweiten pro Quelle?
SELECT source, count(*) FROM insights.part_lifetime_oem GROUP BY source;

-- Welche Verbrauchsmaterialien passen zu einem Drucker?
SELECT part_category, color_channel, part_number, nominal_lifetime_pages, iso_standard
FROM insights.vw_printer_supplies
WHERE printer_model = 'Lexmark CX950se'
ORDER BY part_category, color_channel;
```
