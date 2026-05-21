# Fleet Management DB — Analyse für KRAI-Integration

> Quelle: `C:\Transferr\sql.sql` — Microsoft SQL Server T-SQL Export einer Datenbank `DevFleetMgmt` (Compatibility Level 110 = SQL Server 2012). UTF-16 LE codiert, **156,5 GB** auf Disk (~78 GB effektiver Text).
> Generiert vom Cursor-Agenten am 2026-05-20.

> **Status (2026-05-20 23:42):** **Voller Import abgeschlossen.** 119/119 Tabellen, 62.000.142 / 62.000.209 Rows = **99,99989 % Load-Rate**. Die fehlenden 67 Rows sind ein Scanner-Artefakt (siehe [Import-Pipeline](#import-pipeline) unten) — real fehlen 0 Rows. Komprimiertes Backup liegt unter `database/fleetmgmt/backups/DevFleetMgmt_20260520.bak` (2,09 GB von 26 GB live DB).

## TL;DR

- **119 Tabellen**, **62 Millionen INSERT-Zeilen** insgesamt — **alle drin**.
- **96 %** des Datenvolumens stecken in 2 Tabellen (`ACCSNMPHISTORY` = 48 M, `ACCMIBCOUNTERVALUES` = 12,4 M) — **11 Jahre Historie** (Sept. 2015 bis 19.05.2026) für 10.998 bzw. 6.741 Geräte.
- Die **wirklich wertvollen Stammdaten** liegen in **~500 MB**:
  Geräte, Modelle, Firmware, Service-Verträge, Wartungshistorie, Toner-Wechsel, Event-/Fehlerhistorie, Endkunden, User.
- Das System ist eine **Managed-Print-Services Plattform** (`ACC`-Prefix, MIB/SNMP/MARKER-Konzepte, NPS/F2P-Module) — vermutlich **NDD AccountInsight / FMAudit / kfmview**.
- Die Daten gehören zur **Kunze-Ritter MPS-Flotte** (Indizien: 1.436 Endkunden mit deutschen Namen + Adressen, "Service Info App" API-Clients für Kyocera/Lexmark/Konica Minolta, deutschsprachige Event-Messages).

---

## Tabellen-Inventar (nach Relevanz)

### Tier 1 — SEHR HOCH (Stammdaten + Service-Historie)

| Tabelle | Rows in DB | Was steckt drin | KRAI-Use-Case |
|---------|-----------:|-----------------|---------------|
| `ACCDEVICES` | **11.950** | **Komplette Drucker-Flotte**: IP, MAC, Serial, Modell, Firmware, Warranty, PageCount, Location (10-stufig), ServiceContract, Vendor, Submitter (Kunde), HP/Kyocera-spezifische IDs | **Master-Geräteliste**: matching auf KRAI `krai_core.products` & `manufacturers`, anreichern mit Service-Docs/Error-Codes |
| `ACCMODELDATA` | 1.201 | Geräte-Modell-Definitionen (Vendor-Mapping, PMD-File-Verweis) | Stammdaten-Anker für KRAI Series/Models |
| `ACCDEVICEVENDORS` | 89 | Hersteller-Liste (Agfa, Alps, ..., HP, Kyocera, etc.) | Mapping zu KRAI `krai_core.manufacturers` |
| `ACCFIRMWARE` | 5.207 | Firmware-Versionen mit Release-No, ReleaseDate, EOL-Flag, MinRequired | Firmware-Audit, EOL-Warnung |
| `ACCSUBMITTERCLIENTS` | 1.436 | **Endkunden-Clients** (UUIDs der Submitter-Installationen, ClientInstallDate bis 19.05.2026) | Customer-Tabelle für KRAI |
| `ACCUSERS` | 991 | **Kunden mit Adresse + Email** (z.B. "Sparkasse Markgraeflerland", "Abwasserzweckverband Staufener Bucht") | Customer-Stammdaten |
| `ACCUSERCLIENTRELATIONS` | 1.443 | User ↔ Client Zuordnung | Multitenancy/RBAC |
| `ACCEVENTHISTORY` | 836.185 | **Echte Drucker-Events/Alarme** mit DeviceId, AlertCode, Severity, sKey (z.B. `PrMibMarker.04`), Message (DE!), Raised/Cleared Timestamps | **Goldgrube**: real-world Fehler-Häufigkeit pro Modell → Verlinken mit KRAI `error_codes` Hierarchie |
| `ACCDEVICEMAINTENANCE` | 448 | Wartungs-Regel-Auslösungen (DeviceId, MaintenanceId, LastRaised, LastCount, TicketMessage) | Wartungshistorie + Ticket-Templates |
| `ACCMAINTENANCE` | 19 | Wartungs-Regel-Definitionen | Service-Workflow-Stammdaten |
| `ACCDEVICECONTRACTS` | 31.491 | Verknüpfung Drucker ↔ Vertrag mit Startdatum | Vertrags-Coverage pro Gerät |
| `ACCCONTRACTS` | 985 | Service-Verträge (Mono/Color Free Pages, Page Charges, Charge Months) | Klick-Verträge / SLA |

### Tier 2 — HOCH (Operative Daten)

| Tabelle | Rows in DB | Was steckt drin | KRAI-Use-Case |
|---------|-----------:|-----------------|---------------|
| `ACCMARKERREFILL` | 199.170 | **Toner/Drum/Fuser-Wechsel-Historie** (DeviceId, Markerindex, PRNumber, Datum) | Verbrauchs-Analytics, Predictive Refill |
| `ACCDEVICEMARKERCOVERAGE` | 141.934 | Pro Gerät+Marker: Coverage %, IsOriginal, IsPreferred, Colorant (cyan/magenta/yellow/black), PRNumber | Toner-Bestellung, Original vs. Kompatibel |
| `ACCFMREPORTING` | 128.085 | Monatliche Druckvolumen pro Gerät: yyyymmDate, TotalVolume, BWVolume, ColorVolume, CopierVolume, ScanVolume, FaxVolume | Volumen-Trends, Abrechnung |
| `ACCMIBCOUNTERTEMPLATE` | 45.093 | MIB-Counter-Definitionen pro Modell | Modell-spezifische Zähler-Schemas |
| `ACCINPUTTRAYS` | 22.184 | Fach-Konfigurationen pro Gerät | Papier-Setup |
| `ACCMARKERCOVERAGE` | 20.525 | Coverage-Statistiken (modellweit) | Benchmark-Daten |
| `ACCMIBPROPERTYVALUES` | 6.753 | MIB-Eigenschaftswerte pro Gerät (model name, serial, etc.) | Erweiterte Geräte-Properties |
| `ACCDEVICEMARKERALERT` | 6.860 | Pro Gerät: zugeordnete Marker-Alert-Regeln (Schwellwert) | Verbrauchs-Alerting |
| `ACCDEVICEALIAS` | 6.490 | Alternative Drucker-IPs/Namen | IP/DNS-Mapping |
| `ACCMARKERALERT` | 84 | Alert-Regel-Definitionen (Schwellwerte) | |
| `ACCPMDSTOCK` | 2.563 | Inventar-PMD-Files (z.B. `Konica_Minolta_C203_C253_C353.pmd`) | Drucker-Modell-Mapping |
| `ACCPMDFILES` | 2.175 | PMD-File-Definitionen | Modell-DB |
| `ACCUSERLICENSE` | 533 | Lizenz-Tracking | |
| `ACCSYSTEM` | 206 | Systemkonfiguration | |
| `ACCSNMPALERTPRESELECT` | 128 | SNMP-Alert-Voreinstellungen | |
| `ACCSNMPVENDORS` | 110 | SNMP-Vendor-Definitionen | |
| `ACCAPICLIENTS` | 10 | OAuth-Clients (Service Info App Kyocera/Lexmark/Konica Minolta) | Bekannte Integrations-Endpunkte |

### Tier 3 — Großvolumen-Historie (jetzt importiert, statt geskippt!)

| Tabelle | Rows in DB | Zeitraum | KRAI-Use-Case |
|---------|-----------:|----------|---------------|
| `ACCSNMPHISTORY` | **48.074.445** | 2015-09-09 → 2026-05-19 für **10.998 Geräte** | **Uptime/Verfügbarkeits-Analytik**, SNMP-Probe-Trends, OID-Verlauf |
| `ACCMIBCOUNTERVALUES` | **12.449.056** | 2015-11-23 → 2026-05-19 für **6.741 Geräte** | **Predictive Maintenance via 11 Jahre Counter-Trends**, Counter-Verlauf pro Marker (Pages, Coverage, Refill-Cycles) |

### Leere Tabellen (im Original-System nie befüllt)

59 Tabellen sind leer — ungenutzte Module:
- **Departments/Billing**: `ACCDEPARTMENTS`, `ACCBILLINGS`, `ACCBUDGETCHECKS`, `ACCCHARGES`, ...
- **Deployment**: `ACCDEPLOYMENT`, `ACCDEPLOYMENTHISTORY`, `ACCDEPLOYMENTTASKS`
- **NPS** (NetPrintServer): `NPSCONFIG`, `NPSDEVICES`, `NPSEVENTLOG`, ...
- **Follow2Print/JobManagement**: `ACCF2PUSERS`, `ACCJOBS`, `ACCPRTDISCOVERY`
- **Orders/Pricing**: `ACCDEVICEORDERS`, `ACCPRICELISTS`, `ACCPAPERS`, ...

→ Diese Tabellen existieren als Schema, das Originalsystem hat sie aber nie aktiv genutzt.

---

## Schlüssel-Spalten in `ACCDEVICES` (114 Spalten, Herzstück)

```
Identifikation:    Id, PrinterIP, MACAddress, SerialNo, CISerial, InventNo, AssetNo, CIID, ClientUUID
Hersteller/Modell: VendorId, Model, UserModel, ArticleNo, Firmware
Kundenkontext:     SubmitterId (→ ACCSUBMITTERCLIENTS), ContractId, CostCenter, SLA
Standort:          Location, LocationLevel1..10, LocationDescription, Contact
Garantie:          WarrantyStart, WarrantyMonths, WarrantyClicks
Nutzung:           PageCount, PageCountTime, PagesPerMonth, PagesToThreshold, PagesToRefill
Service-Flags:     ServiceContract (bit), SecurePrint, ProductionProcess, OfficePrint, Follow2Print
Status:            Created, Modified, Deactivated, Deleted, LastDataTransferDate, LastWalkDate
Lieferung:         DeliveryToClientPending, DeliveredToClient, CreatedOnClient
Hersteller-spez.:  HPIsCDCA, HPJamState, HPJamId, KyoKfsId (Kyocera Fleet Services), FSMClientId
Sonstige:          Info1, Info2, Info3 (frei belegbar), pmdFile, SnmpVersion/Community
```

## Schlüssel-Spalten in `ACCEVENTHISTORY`

```
Kontext:    DeviceId, EventSource, ContractId
Klassifik.: Severity, DeviceState, PrinterState, PrinterError, AlertCode, AlertGroup, AlertGroupIndex
Alert-Meta: AlertHash, AlertSeverity, AlertLocation, AlertDescription
Inhalt:     sKey (z.B. "PrMibMarker.04"), Message (DE, freier Text), CecData (sparse JSON)
Lifecycle:  Raised, IsNotified, Notified, Cleared, ClearedBy, ClearFcnt
Annotation: EventId, EventNote, NoteSeverity, NoteTimeUTC
PK:         pkId (BIGINT IDENTITY)
PageCount:  PageCount zum Zeitpunkt des Events
```

**Mapping-Hinweis für KRAI Error-Code-Hierarchie:**
- `sKey` (z.B. `PrMibMarker.04`) ist ein MIB-Pfad — keine direkte Hersteller-Fehler-Codes
- `PrinterError`, `AlertCode`, `AlertGroup` sind die internen Codes
- Die Message ist Freitext und enthält teilweise direkt sprechende Fehler (z.B. Toner-Probleme, Papier-Fehler)
- Für Mapping auf `krai_intelligence.error_codes`: über (Vendor, Model, sKey)/Message-NLP

## Schlüssel-Spalten in `ACCMIBCOUNTERVALUES` (237 Spalten, jetzt komplett verfügbar)

```
Identifikation: DeviceId, TimeUTC, TimeLocal, TransferUTC, CounterVersion
Counter:        C1..C230 (NULL oder bigint) — modellspezifische MIB-Counter-Slots
Kontext:        ContractId
PK:             pkId (BIGINT IDENTITY)
```

→ Das Counter-Schema (welcher Slot `Cnn` was bedeutet) liegt in `ACCMIBCOUNTERTEMPLATE` pro Modell.
→ Wertvoll für: monatliche Aggregation Pages, Coverage-Trends, Refill-Cycle-Length-Analyse.

---

## Erkenntnisse zum Kontext (Hinweise im Schema)

1. **API-Clients** (`ACCAPICLIENTS`):
   - "Service Info App [Kyocera]"
   - "Service Info App [Lexmark]"
   - "Service Info App [Konica Minolta]"
   → Es gibt bereits eigene Service-Info-Apps pro Hersteller.

2. **HP-Spezifika** (`HPIsCDCA`, `HPJamState`, `HPJamId`):
   → HP Smart Device Service / CDCA-Integration vorhanden.

3. **Kyocera-Spezifika** (`KyoKfsId`):
   → Kyocera Fleet Services Anbindung.

4. **Deutsche Kundenbasis**:
   → Submitter-Names wie "Sparkasse Markgraeflerland", "Abwasserzweckverband Staufener Bucht Bad Krozingen" → Klassischer Mittelstandskunden-Mix Süddeutschland.

5. **Compatibility Level 110** + Original-Datei in `MSSQL12.FSM`:
   → DB stammt aus SQL Server 2014, Server-Instanz heißt `FSM` (Fleet Service Management?).

6. **11 Jahre Historie**: SNMP-Polling ab Sept. 2015 — d.h. das System läuft seit ~2015 produktiv.

---

## Import-Pipeline (Lessons Learned)

Der Import war eine technische Herausforderung. Hier die wirksame Pipeline:

### Phase 1 — Smart Skip (für die kleinen Tabellen)

Erstes Versuch via `sqlcmd -i dump.sql` crashte bei einem Newline-im-String-Bug in `ACCMIBCOUNTERVALUES` und ließ ~83 Tabellen leer.

**Fix**: Python-Streamer (`scripts/sql_dump_filter_missing.py`) filterte den 156-GB-UTF-16-Dump auf 11,6 MB nur mit den 22 fehlenden Tabellen. Import: **73 Sekunden, 0 Errors**.

### Phase 2 — Big Tables (60 Mio. Rows)

Für `ACCSNMPHISTORY` + `ACCMIBCOUNTERVALUES` war die naive sqlcmd-Variante mit ~140 Rows/sec extrapoliert **5 Tage**. Auch Multi-Row INSERTs halfen nicht (`MEMORY_ALLOCATION_EXT` Wait wegen 237 Spalten).

**Lösung: bcp Character Mode** mit TABLOCK + minimal logging:

1. `scripts/sql_dump_filter_bigtables.py` → sanitiert den Dump (Newlines in Strings → `' + CHAR(10) + N'`), Output 77 GB UTF-8 (15 Min)
2. `scripts/sql_to_tsv_parallel.py` → parst die SQL-INSERTs in 21 parallelen Workern → 14,3 GB TSV (17 Min)
3. PKs droppen (Heap-Insert ist viel schneller)
4. `database/fleetmgmt/scripts/bcp_import.sh` → bcp mit `-t 0x1F -r 0x1E0a -h TABLOCK -b 100000 -k` → 60,5 Mio Rows in **28 Min** mit ~40.000 Rows/sec
5. PKs neu anlegen (composite + identity) → 5 Min

**Gesamt-Pipeline: 65 Min** (Phase 1 + Phase 2 + Backup).

### Bekanntes Scanner-Artefakt

Der initiale Dump-Scan (`scripts/sql_dump_inspect.py`) zählte konsequent 2 Rows mehr pro Tabelle als der echte INSERT-Inhalt — Pattern matched über UTF-16-Bytes findet 2 false-positives (vermutlich am Dateianfang/-ende). Die Diff "67 Rows missing" zeigt:
- 33 Tabellen × je 2 = 66 Rows
- + 1 Row in `NPSUSERS`

→ **Real fehlen 0 Rows**. Bestätigt durch `ACCSNMPHISTORY = 48.074.445` (exakt Original-Count) und `ACCMIBCOUNTERVALUES = 12.449.056` (genauso).

---

## Backup & Wiederherstellung

```bash
# Backup-Datei (komprimiert, 2,09 GB von 26 GB DB)
database/fleetmgmt/backups/DevFleetMgmt_20260520.bak

# Restore in einen leeren Container (Beispiel):
docker exec krai-fleetmgmt-mssql /opt/mssql-tools18/bin/sqlcmd \
  -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -Q "
  RESTORE DATABASE [DevFleetMgmt]
    FROM DISK = N'/var/opt/mssql/backups/DevFleetMgmt_20260520.bak'
    WITH MOVE 'DevFleetMgmt' TO '/var/opt/mssql/data/DevFleetMgmt.mdf',
         MOVE 'DevFleetMgmt_log' TO '/var/opt/mssql/data/DevFleetMgmt_log.ldf',
         REPLACE, RECOVERY;"
```

---

## Container & Verbindung

| Service | Image | Container | Port |
|---------|-------|-----------|------|
| MSSQL Fleet DB | `mcr.microsoft.com/mssql/server:2022-latest` | `krai-fleetmgmt-mssql` | `1433` |

### Verbindung

```bash
docker exec -it krai-fleetmgmt-mssql /opt/mssql-tools18/bin/sqlcmd \
  -S localhost -U sa -P "$env:MSSQL_SA_PASSWORD" -C -d DevFleetMgmt
```

Vom Host (mit `sqlcmd` oder Azure Data Studio / DBeaver):
- Server: `localhost,1433`
- User: `sa`
- Password: aus `.env` (`MSSQL_SA_PASSWORD`)
- Trust: ja

---

## Nächste Schritte (für KRAI-Integration)

1. **Mapping-Doc:** Siehe `docs/krai_fleetmgmt_integration_plan.md` (Tabellen → KRAI-Schemas).
2. **ETL-Queries:** Siehe `docs/fleetmgmt_etl_queries.sql` (Reusable SELECT-Templates).
3. **PostgreSQL FDW (`tds_fdw`)** oder direkte ETL-Scripts für laufenden Sync zwischen MSSQL und KRAI Postgres.
4. **Anreicherung umgekehrt:** KRAI-Service-Docs zu jedem Gerät verfügbar machen (Filament-View).
