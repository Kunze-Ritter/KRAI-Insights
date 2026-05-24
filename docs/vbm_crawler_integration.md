# VBM-Crawler-Anbindung (Lexmark, später HP/Canon/KM)

> **Status:** Branch `feat/vbm-crawler-supplies`, Migration **047** angewendet,
> 845 Lexmark-Reichweiten + 5.990 Kompatibilitäts-Zeilen in der Insights-DB
> verifiziert (Stand 2026-05-23).
>
> Diese Doku erklärt **was** importiert wird, **warum** so importiert wurde
> (Architekturentscheidungen + Trade-offs) und **wie** ein Entwickler die
> Änderung testet / mergt / zurückbaut.

## TL;DR

KRAI-Insights hatte bisher nur für **Konica Minolta** OEM-Soll-Reichweiten
(aus einer KM-Excel via `krai_pm.part_lifetimes`). Damit die Garantie-/Frühausfall-
Auswertungen (Migrationen 037/038/045) auch für **Lexmark, HP, Canon** greifen,
braucht es Soll-Werte für diese Hersteller. Wir ziehen sie nicht aus PDFs oder
einer Excel, sondern crawlen sie direkt von den Hersteller-Websites — im
Schwester-Repo [`KRAI-Crawler-VBM`](https://github.com/KR-AI/KRAI-Crawler-VBM)
(node/TypeScript, sibling-Folder zu diesem Repo).

Diese PR ist die **Brücke**: Crawler-JSON → `insights.part_lifetime_oem` +
neue `insights.part_compatibility`-Tabelle für die m:n-Beziehung
Supply ↔ Drucker. Implementiert für **Lexmark de_DE** (845 SKUs / 513 Drucker);
HP/Canon/KM folgen ohne Schema-Änderung.

## Motivation / Hintergrund

KRAI-Insights' bisherige Soll-vs-Ist-Logik (Migration **038**) ist
herstellerneutral geschrieben — sie joint über
`manufacturer ILIKE 'X%' + part_category` aus `part_lifetime_oem`. Sie funktioniert
heute aber nur für KM, weil nur KM dort Werte hat. Folge:

- `vw_part_early_failures` mit `basis = 'OEM-Soll (Seiten)'` gibt es nur für KM.
- Für Lexmark/HP fällt die View auf die Heuristik `basis = 'Zeit (1 Jahr)'` zurück
  — was laut 045-Review systematisch heavy-use-normal-wear falsch als
  Garantiefall labelt.
- Migration **046** (`vw_lagebericht.ersatzteil_fruehausfaelle`) zählt nur
  noch konfidenz-validierte Fälle — d. h. ohne Soll-Daten für Lexmark/HP
  taucht dort gar nichts auf.

Mit dem VBM-Crawler liefern wir die fehlende OEM-Seite und füllen damit eine
echte Datenlücke — nicht eine ETL-Spielerei.

## Was wurde geändert

```
db/migrations/047_vbm_crawler_supplies.sql        [NEU]
insights/etl/vbm_crawler_extractor.py             [NEU]
insights/etl/load.py                              [GEÄNDERT — siehe unten]
insights/core/config.py                           [GEÄNDERT — 1 Setting]
docker-compose.yml                                [GEÄNDERT — Volume-Mount]
.env.example                                      [GEÄNDERT — 2 neue Vars]
docs/vbm_crawler_integration.md                   [diese Datei]
.cache/vbm-crawler/.gitkeep                       [Placeholder für Default-Mount]
```

**Zusätzliche Änderung in `load.py` außerhalb des reinen Neu-Imports:**
`load_part_lifetimes()` wurde von `TRUNCATE insights.part_lifetime_oem` auf
`DELETE WHERE source LIKE 'km_excel%'` umgestellt — sonst würde der KM-Loader
beim nächsten Aufruf alle VBM-Crawler-Daten in derselben Tabelle wegputzen.
Verifiziert: `source = 'km_excel_v1.18'` (126 Zeilen) wird vom LIKE-Filter
korrekt erfasst.

## Architektur

```
KRAI-Crawler-VBM/output/             ← Sibling-Repo, schreibt JSON pro Hersteller
├── lexmark/supplies/*.json           (eine Datei pro SKU — Stand 23.5.2026: 849)
├── supplies-master.json              (konsolidiert; 849 Einträge)
├── alias-index.json
└── by-printer.json
            │  ← read-only Volume-Mount (docker-compose) auf /srv/vbm-crawler/
            ▼
insights/etl/vbm_crawler_extractor.py ← liest supplies-master.json, mappt Schema
            ▼
insights/etl/load.py::load_vbm_crawler() ← DELETE-by-source + UPSERT
            ▼
insights.part_lifetime_oem        (845 Lexmark + 126 KM = 971 Zeilen)
insights.part_compatibility       (5.990 Lexmark-Zeilen, 513 unique Drucker)
            ▼
insights.vw_printer_supplies      (Komfort-View "welche Toner passen zu Drucker X")
+ vw_part_oem_comparison (037), vw_part_early_failures (045/038)
  bekommen Lexmark-Soll automatisch (manufacturer ILIKE 'Lexmark%')
```

## Schlüsselentscheidungen & Begründungen

Diese Sektion ist das Kernstück der Doku — was hätten wir auch anders machen
können, und warum ist es so geworden.

### E1 — Selektives DELETE statt TRUNCATE im KM-Loader

**Problem:** Der bestehende `load_part_lifetimes()` macht
`TRUNCATE insights.part_lifetime_oem`. Wenn parallel VBM-Crawler-Daten in
derselben Tabelle leben, sind die nach dem nächsten KM-Lauf weg.

**Alternativen:**

1. **Eigene Tabelle `vbm_supply_lifetimes`** — Duplizierung des Schemas,
   alle existierenden Views (037/038/045) müssten als UNION über zwei Tabellen
   umgeschrieben werden. Mehr Code, mehr Wartung, keine echter Mehrwert.
2. **TRUNCATE belassen, KM-Loader nicht mehr nutzen** — bricht ein bestehendes
   Feature ab, das funktioniert.
3. ✅ **Selektives DELETE per `source LIKE`** — minimal-invasiv: KM nutzt
   `'km_excel_v*'`, VBM-Crawler nutzt `'vbm_crawler:<vendor>_v*'`, beide
   können nebeneinander leben. Beide Loader putzen nur ihre eigenen Daten.

**Konsequenz:** Bestehender KM-Loader-Code hat sich um genau **einen** SQL-Befehl
geändert (TRUNCATE → DELETE WHERE). Verhalten ist identisch, solange KM die
einzige Quelle ist.

### E2 — Partial Unique Index statt globalem UNIQUE

**Problem:** Für sauberes UPSERTen brauchen wir `UNIQUE(manufacturer, part_number)`.
Die KM-Daten enthalten aber Duplikate (DR-512-M 6× mit identischem Tripel,
60× Zeilen mit leerer `part_number = ''` für Konica Minolta). Ein globaler
UNIQUE würde retroaktiv fehlschlagen (live verifiziert während der ersten
Migration-Anwendung).

**Alternativen:**

1. **KM-Daten dedupen vor UNIQUE** — riskant, weil unklar ist, ob die
   Excel-Duplikate "Daten-Müll" oder absichtlich (z. B. Farb-Varianten ohne
   `color_channel`) sind. Entscheidung sollte beim KM-Domain-Owner liegen,
   nicht beim VBM-Integrator.
2. ✅ **Partial Unique Index `WHERE source LIKE 'vbm_crawler:%'`** —
   garantiert Deduplikation **nur** für unsere Quelle. KM bleibt unangetastet.
   Die UPSERT-Klausel im Loader spiegelt die WHERE-Bedingung
   (`ON CONFLICT (mfr, pn) WHERE source LIKE 'vbm_crawler:%'`) — Standard
   PostgreSQL.

**Konsequenz:** Falls jemand später die KM-Duplikate aufräumt, kann der Index
zum globalen UNIQUE promoted werden — ein einzeiliger Migration-Drop+Recreate.

### E3 — Neue Tabelle `part_compatibility` statt CSV in `model_family`

**Problem:** Lexmark-Realität ist 1 Toner → 5–20 Drucker (z. B. CX950/951/833
teilen mehrere SKUs). Das bestehende `model_family`-Feld in `part_lifetime_oem`
ist ein VARCHAR(60) — designed für **eine** Modell-Serie pro Eintrag.

**Alternativen:**

1. **`model_family` mit kommasepariertem String** — Query "welche Toner passen
   zu CX950se" wird zu `WHERE model_family ILIKE '%CX950%'`, brüchig bei
   ähnlichen Modellen (CX950 matched auch CX9500), keine FK, schlechte
   Performance bei vielen Druckern.
2. **JSONB-Spalte** — bessere Suche, aber inkompatibel mit dem KM-Schema
   (das vorhandene `model_family` ist Plain-String).
3. ✅ **Eigene m:n-Tabelle `part_compatibility`** — der natürliche relationale
   Weg. Erlaubt indizierte Suche in beiden Richtungen ("welche Toner für
   Drucker X" + "welche Drucker für SKU Y"), trägt Vendor-Printer-IDs als
   FK-Kandidaten für eine spätere Verknüpfung mit `devices_unified` /
   `model_catalog`.

**Konsequenz:** Die View `vw_printer_supplies` ist die Komfort-Abstraktion.
KM-Daten ohne Compatibility-Zeilen bleiben unverbunden — sie tauchen nur in
`part_lifetime_oem` auf, nicht in der Drucker-Sicht. Das ist okay, weil KM-Soll
heute primär für Toner-Yield-vs-OEM via `oem_target_pages` in
`vbm_lifecycle_events` (FleetMgmt) genutzt wird, wo der Bezug aufs Gerät schon
da ist.

### E4 — JSON-Datei als Crawler↔Insights-Vertrag, kein direkter DB-Schreib

**Problem:** Der VBM-Crawler ist node/TypeScript, Insights ist Python/SQLAlchemy.
Theoretisch könnte der Crawler auch direkt in Postgres schreiben.

**Alternativen:**

1. **Crawler schreibt direkt in Postgres** — Crawler kennt das Insights-Schema,
   tight coupling. Crawler-Repo bräuchte Postgres-Credentials.
2. **Crawler füllt Zwischen-Tabelle in KRAI-PG (`krai_pm.supplies_raw`)** — analog
   KM-Pattern. Aber `krai_pm` ist laut Guardrail read-only von Insights aus,
   und der Crawler ist nicht KRAI-PM-Owner. Doppelte Brücke (Crawler → KRAI-PG
   → Insights) ohne Mehrwert.
3. ✅ **JSON-Datei als versionierter Vertrag** — Crawler schreibt
   `output/supplies-master.json` mit dokumentiertem Schema (im Crawler-README).
   Insights liest das. Vorteile: Crawler ist self-contained, das JSON ist
   git-tauglich (für CI-Snapshot-Tests), inkrementelle Re-Imports trivial,
   Crawler kann unabhängig auf einem anderen System laufen.

**Konsequenz:** Die einzige Kopplung ist das JSON-Schema. Wenn der Crawler
ein Feld umbenennt, fehlt das in unserem Extractor — wirft keinen Fehler,
nur eine `None`-Aufzeichnung. Schemabrüche sollte man im Crawler-README
versionieren (`v0.1` Suffix im `source`-String ist dafür vorbereitet).

### E5 — Pfadkonfiguration: Volume-Mount mit `${VBM_CRAWLER_OUTPUT_HOST}` + Default-Fallback

**Problem:** Im Docker-Stack ist der Sibling-Folder `../KRAI-Crawler-VBM/output`
nicht sichtbar, weil das App-Container-Bind nur `./` mountet.

**Alternativen:**

1. **`./:/app` Mount ausreichend, Crawler-Output in `./.cache/` kopieren** —
   manueller Sync-Schritt nötig, der vergessen wird.
2. **Crawler in Insights-Docker-Stack einbinden** — Crawler-Lifecycle koppelt
   sich an Insights, viel mehr Compose-Komplexität.
3. ✅ **Optionaler Volume-Mount mit Env-Variable** — `VBM_CRAWLER_OUTPUT_HOST`
   in `.env` zeigt auf den Host-Pfad, Docker mountet das read-only auf
   `/srv/vbm-crawler/`. Default-Fallback ist `./.cache/vbm-crawler/`
   (mit `.gitkeep`) — damit der Mount immer funktioniert, auch wenn die
   Var leer ist. Loader meldet dann höflich "Master nicht gefunden" statt zu
   crashen.

**Konsequenz:** Drei sinnvolle Setups werden alle abgedeckt:
- Docker mit gemounteten Crawler-Output (Production-Dev),
- Docker ohne Crawler (Var leer, Loader skipped),
- Host/`.venv` (`VBM_CRAWLER_OUTPUT_DIR=` leer → Sibling-Default greift).

## Migration 047 im Detail

```sql
-- 1) part_lifetime_oem um optionale Crawler-Felder erweitern (alle NULLable)
ALTER TABLE insights.part_lifetime_oem
    ADD COLUMN IF NOT EXISTS supply_color  VARCHAR(20),
    ADD COLUMN IF NOT EXISTS yield_variant VARCHAR(20),
    ADD COLUMN IF NOT EXISTS iso_standard  VARCHAR(40),
    ADD COLUMN IF NOT EXISTS source_url    TEXT;

-- 2) Partial Unique Index nur für unsere Quelle (siehe E2)
CREATE UNIQUE INDEX IF NOT EXISTS uq_part_lifetime_oem_vbm
    ON insights.part_lifetime_oem (manufacturer, part_number)
    WHERE source LIKE 'vbm_crawler:%';

-- 3) Neue m:n-Tabelle (siehe E3)
CREATE TABLE IF NOT EXISTS insights.part_compatibility ( ... );

-- 4) Komfort-View
CREATE OR REPLACE VIEW insights.vw_printer_supplies AS ...;
```

Volltext: [`db/migrations/047_vbm_crawler_supplies.sql`](../db/migrations/047_vbm_crawler_supplies.sql).

## Schema-Mapping (Crawler-JSON → Insights)

| Crawler-Feld (JSON) | `part_lifetime_oem`-Spalte | Notes |
|---|---|---|
| `vendorLabel` ("Lexmark") | `manufacturer` | 1:1 |
| `supplyType` | `part_category` | mapped: `toner`/`ink`→`toner`, `drum`→`drum`, **`imaging_unit`/`imaging_kit`→`imaging_unit`** (Drum+Dev kombiniert, ≠ reine Trommel — siehe unten), `developer`→`developing_unit_bw`, `fuser`/`maintenance_kit`→`fuser`, `transfer_belt`/`transfer_kit`→`transfer_belt`, `waste_container`→`waste`, `staple_cartridge`→`staple` |
| `supplyCode` ("79L2HK0") | `part_number` | 1:1, Vendor-SKU |
| `yieldPages` (Integer) | `nominal_lifetime_pages` | NULL-Werte werden ausgefiltert (4 Einträge betroffen: 1 Farbband, 2 Fotoleiter, 1 Resttoner) |
| `color` ("black"/"cyan"/...) | `color_channel` | mapped: `black`→`bw`, `cyan`→`c`, `magenta`→`m`, `yellow`→`y`, `tricolor`→`col`, `unknown`→NULL |
| `color` (Rohwert) | `supply_color` | neu — vollständige Farbe für Debugging |
| `yieldVariant` | `yield_variant` | aktuell selten gesetzt, Reserve |
| `isoStandard` ("ISO/IEC 19798") | `iso_standard` | direkt aus Lexmark-Spec extrahiert, nicht geraten |
| `sourceUrl` | `source_url` | für Audit |
| — | `source` | `"vbm_crawler:<vendor>_v0.1"` (z. B. `lexmark`, `hp`) |

`compatiblePrinters[]` → Zeilen in `part_compatibility` (m:n):

| JSON | Spalte |
|---|---|
| `vendorLabel` | `manufacturer` |
| `supplyCode` | `part_number` |
| `color` (gemappt) | `color_channel` |
| `compatiblePrinters[].model` | `printer_model` |
| `compatiblePrinters[].vendorPrinterId` | `vendor_printer_id` |
| `compatiblePrinters[].url` | `printer_url` |

## Teiltyp-Taxonomie: Imaging Unit ≠ Trommel (Migration 048)

Eine **Imaging Unit** ist **Drum + Developer in EINEM Bauteil** (z. B. Lexmark
MS/MX-Mono: „Belichtungseinheit"). Bei anderen Modellen sind **Trommel**
(Fotoleiter/photoconductor) und **Entwicklereinheit** getrennte Teile. Das sind
also drei distinkte Teiltypen — eine Imaging Unit ist *keine* (reine) Trommel.

Bis Migration 047 wurden Imaging Units auf **beiden** Join-Seiten mit reinen
Trommeln vermischt (Extractor `imaging_unit→drum`; `insights.part_type()` seit
031 `…imaging…→'Trommel/Drum'`). **Migration 048** trennt das:

- **Crawler** (`detectSupplyType`, KRAI-Crawler-VBM): „Belichtungseinheit" →
  `imaging_unit` (vorher fälschlich `drum`); „Fotoleitereinheit"/photoconductor
  bleibt `drum`. Bei Lexmark: 47 „drum" → **25 echte Trommeln + 22 Imaging Units**.
- **Extractor**: `imaging_unit`/`imaging_kit` → part_category `imaging_unit`.
- **`insights.part_type()`**: neuer Teiltyp `'Imaging Unit'` (geprüft VOR
  Toner/Trommel/Entwickler; erkennt `imaging unit`/`belichtungseinheit`/
  `bildeinheit`/… ); der Trommel-Zweig erkennt jetzt auch `fotoleiter`/`photoconductor`.
- **`vw_spare_part_events`** OEM-CASE: `imaging_unit` → `'Imaging Unit'`.

Wirkung (Lexmark, gemessen): die früher als „Trommel/Drum" zusammengeworfenen
OEM-gestützten Frühausfälle splitten korrekt in **Trommel/Drum (9 Zeilen/3 Geräte)
+ Imaging Unit (1/1)**, je gegen ihr *eigenes* OEM-Soll.

> KM-Hinweis: die KM-Excel-Kategorie `image_unit_color` bleibt vorerst auf
> `'Trommel/Drum'` (KM-Produktsemantik unverifiziert) — separat zu prüfen.

## Abdeckung: Verschleißteile aus `/printers/accessory/` (Fuser, Transfer, Maintenance)

Lexmark listet **Toner, Imaging Units, Developer, Waste, Heftklammern** unter
`/printers/supply/` — aber **Fuser, Transferbänder, Fixierstationen, Wartungs-/
Maintenance-Kits** liegen unter `/printers/accessory/` (page-type `accessory`).
Der Crawler `discover()` erfasst daher zusätzlich Accessory-URLs, gefiltert auf
Verschleiß-/Wartungs-Schlagworte (`fuser|fixier|transfer|maintenance|wartung|belt|
entwickl|bilduebertrag`), damit Nicht-Verbrauchsmaterial (Fächer, Speicher,
Tastaturkits, Kabel) draußen bleibt.

Besonderheiten dieser Seiten (im Crawler/Parser berücksichtigt):
- Reichweite steht als **„Durchschnittliches Druckvolumen"** (nicht „Reichweite").
- `detectSupplyType` ist bindestrich-tolerant (`Transfer-Kit`/`Transfer-Belt`),
  kennt den `fixier`-Stamm (Fixierstation) und `Transfermodul`, und prüft
  `maintenance_kit` **nach** transfer/fuser (damit „Transfer-Belt-Wartungskit"
  als Transferband zählt, nicht als generisches Maintenance-Kit).
- Extractor-Mapping: `fuser`/`maintenance_kit` → `fuser`, `transfer_belt`/
  `transfer_kit` → `transfer_belt` (Insights-Teiltypen `'Fixiereinheit'`/`'Transfer'`).

Datenwirkung (Lexmark, Mai 2026): neu **fuser 61** (Median ~200.000 S., inkl.
Maintenance-Kits), **transfer_belt 6** (~120.000 S.); developer 19→22.
Garantie-Frühausfälle gewinnen dadurch OEM-gestützte Tiers, die es vorher nicht
gab: **Fixiereinheit 9 Geräte `konfidenz='hoch'`** + **Transfer 1** (vorher null,
weil keine Lexmark-Soll-Werte für diese Teiltypen existierten).

> Noch nicht abgedeckt: ADF-/Scanner-Wartungskits landen mangels eigenem
> Teiltyp als `maintenance_kit → 'Fixiereinheit'` (Näherung). Reine
> Nicht-Verbrauchsteile (Trays/Speicher) bleiben bewusst außen vor.

## Setup (Docker)

`.env`:
```
VBM_CRAWLER_OUTPUT_HOST=C:\Github\KRAI-Crawler-VBM\output
VBM_CRAWLER_OUTPUT_DIR=/srv/vbm-crawler
```

```powershell
# Container neu erstellen, damit Mount + Env greifen
docker compose up -d app

# Migration anwenden (einmalig)
docker exec krai-insights-app python scripts/migrate.py

# Import (idempotent, beliebig oft wiederholbar)
docker exec krai-insights-app python -m insights.etl.load --vbm-crawler
```

Erwartete Ausgabe nach erstem Lauf:
```
VBM-Crawler liefert 845 Reichweiten (uebersprungen ohne Yield: 4)
VBM-Crawler liefert 5990 Kompatibilitaets-Zeilen
VBM-Crawler-Import: 845 Reichweiten, 5990 Kompatibilitaets-Zeilen
```

## Setup (Host / venv)

```powershell
# .env: VBM_CRAWLER_OUTPUT_DIR leer lassen → Sibling-Default greift
& .venv\Scripts\python.exe scripts\migrate.py
& .venv\Scripts\python.exe -m insights.etl.load --vbm-crawler
```

## Quick-Check (für Review)

```sql
-- Welche Quellen sind drin?
SELECT source, count(*) FROM insights.part_lifetime_oem GROUP BY source;
--           source           | count
-- --------------------------+-------
--  km_excel_v1.18           |   126
--  vbm_crawler:lexmark_v0.1 |   845

-- KM unverändert?
SELECT count(*) FROM insights.part_lifetime_oem WHERE source LIKE 'km_excel%';
-- 126  (war vorher 126)

-- Drucker-Sicht funktioniert?
SELECT part_category, color_channel, part_number, nominal_lifetime_pages, iso_standard
FROM insights.vw_printer_supplies
WHERE printer_model = 'Lexmark CX950se'
ORDER BY part_category, color_channel;
-- 19 Zeilen: 15 Toner (5 SW + 4 C + 3 M + 3 Y) + 2 Heftklammern + 1 Waste + 1 Photo-Toner
```

## Wirkung auf bestehende Views

Diese Sichten joinen über `manufacturer ILIKE '...%' + part_category` auf
`part_lifetime_oem` — und bekommen daher die Lexmark-Werte **automatisch**:

- **`vw_part_oem_comparison`** (037) — OEM-Soll vs. real, pro
  manufacturer × model × teiltyp. Nach diesem PR taucht Lexmark dort auf,
  sobald entsprechende Einträge in `vw_spare_part_events` (Radix-Material) sind.
- **`vw_part_early_failures`** (045/038) — Frühausfälle. Lexmark-Einträge
  bekommen jetzt `basis = 'OEM-Soll (Seiten)'` statt `'Zeit (1 Jahr)'` —
  also die konfidenz-validierte Variante.
- **`vw_lagebericht.ersatzteil_fruehausfaelle`** (046) — zählt
  konfidenz-validierte Devices. Lexmark-Devices waren bisher unsichtbar
  (nur `konfidenz = 'niedrig'`), tauchen jetzt potenziell als
  `hoch`/`mittel` auf.

**Nichts davon haben wir aktiv neu verdrahtet** — alle bestehenden Views
wirken durch die hinzugekommenen Daten automatisch breiter. Das ist
beabsichtigt.

## Risiko-Assessment / Breaking Changes

| Risiko | Bewertung | Mitigation |
|---|---|---|
| KM-Loader schreibt nicht mehr alle Daten weg | gewollt, siehe E1 | Test: KM-Datenstand vor/nach `--partlifetimes` identisch (manuell verifiziert: 126) |
| Bestehende KM-Auswertungen verändert? | nein — KM-Zeilen bleiben identisch | siehe oben |
| Migration 047 schlägt fehl bei KM-Duplikaten? | war so, ist gefixt mit Partial Index | erste Migration-Anwendung lief grün durch |
| Volume-Mount fehlt → Container-Start crasht? | nein, Default-Fallback `./.cache/vbm-crawler/` mit `.gitkeep` | live getestet |
| Mehrfacher `--vbm-crawler`-Lauf duplizert? | nein, UPSERT via partial UNIQUE | live getestet, 2 Läufe → gleiche Zeilen |
| Crawler-Schema ändert sich später? | source-Spalte trägt Versionssuffix (`vbm_crawler:lexmark_v0.1`) | bei Schemabruch in `v0.2` umstellen, alte Daten per DELETE-by-source bereinigen |
| `part_lifetime_oem` jetzt 8 statt 4 Spalten — bricht ein Importer? | unwahrscheinlich, alle neuen Spalten NULLable + DEFAULT NULL | `_INSERT_PART_LIFETIME` schreibt explizit 7 Spalten (nicht die 4 neuen) — unverändert lauffähig |

## Rollback

```sql
-- DB-Stand vor diesem PR wiederherstellen
DELETE FROM insights.part_lifetime_oem WHERE source LIKE 'vbm_crawler:%';
DROP VIEW IF EXISTS insights.vw_printer_supplies;
DROP TABLE IF EXISTS insights.part_compatibility;
ALTER TABLE insights.part_lifetime_oem
    DROP COLUMN IF EXISTS supply_color,
    DROP COLUMN IF EXISTS yield_variant,
    DROP COLUMN IF EXISTS iso_standard,
    DROP COLUMN IF EXISTS source_url;
DROP INDEX IF EXISTS insights.uq_part_lifetime_oem_vbm;
DELETE FROM insights.schema_migrations WHERE filename = '047_vbm_crawler_supplies.sql';
```

Code: `git checkout main -- insights/etl/load.py insights/core/config.py docker-compose.yml .env.example`
plus `rm insights/etl/vbm_crawler_extractor.py db/migrations/047_*.sql docs/vbm_crawler_integration.md`.

## Nächste Schritte (nach Merge dieses PR)

1. **HP-Crawler** im VBM-Repo implementieren — `learn-about-supplies.ext.hp.com`
   ist die offizielle Page-Yield-Suche von HP und liefert sehr saubere Daten.
   Wenig Aufwand im Insights-Repo: `source = 'vbm_crawler:hp_v0.1'`, Mapping
   in Extractor erweitern, fertig.
2. **Canon & Konica Minolta** über den Crawler — KM ist heute aus Excel, könnte
   mittelfristig auf den Crawler umgestellt werden (dann beides Quellen, vergleichbar).
3. **Lagebericht-Verifikation** — prüfen, ob nach diesem Import in
   `vw_part_early_failures` plötzlich Lexmark-Einträge mit `konfidenz = 'hoch'`
   auftauchen. Wenn ja: Erfolg gemessen.
4. **Crawler-Refresh-Automatik** — der VBM-Crawler ist eine Standalone-CLI;
   ein Nightly-Job (z. B. via Insights-Scheduler-Profile) könnte ihn
   periodisch laufen lassen und danach `--vbm-crawler` triggern.
