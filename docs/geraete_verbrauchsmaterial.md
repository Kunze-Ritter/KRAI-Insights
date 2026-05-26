# Gerät → Verbrauchsmaterial (vw_device_supplies, Migration 051)

> **Status:** Migration **051** angewendet (Stand 2026-05-26).
> Lexmark-Abdeckung **0 % → 92 %**, HP unverändert **99,9 %**.
>
> Diese Doku erklärt, **warum** die naive Verknüpfung Gerät↔Verbrauchsmaterial
> bei Lexmark scheiterte und **wie** `vw_device_supplies` das in drei
> Match-Ebenen löst — datengetrieben, ohne hartkodierte Modell-Mappings.

## TL;DR

Der VBM-Crawler liefert OEM-Reichweiten + Drucker-Kompatibilität
(`part_lifetime_oem` + `part_compatibility` → `vw_printer_supplies`, siehe
[VBM-Crawler-Anbindung](vbm_crawler_integration.md)). Um daraus pro **Flotten-Gerät**
die passenden Verbrauchsmaterialien zu ziehen, braucht es einen Join
`devices_unified.model_display` ↔ `vw_printer_supplies.printer_model`.

Ein **exakter** Join trifft HP zu 99,9 %, **Lexmark aber zu 0 %** — und zwar aus
zwei unabhängigen Gründen, die `vw_device_supplies` beide behebt.

## Das Problem

### 1) Verschmutzter Modellname (Seriennummer + Plattform im Freitext)

FleetMgmt liefert das Lexmark-Modell als Freitext mit angehängter Seriennummer
und Firmware-Plattform-Code:

```
"Lexmark CX735adse 7530529514VH9 CXTMM.250.217"
 └─Marke─┘ └─Modell─┘ └──Serie───┘ └─Plattform─┘
```

`model_display = printer_model` kann das nie treffen (der Crawler kennt nur
`"Lexmark CX735adse"`). HP dagegen liefert `model_display` sauber
(`"HP LaserJet MFP E62665"`) → exakter Match.

### 2) Vertrags-/Enterprise-Umlabelung (XC/XM/M/C-Serie)

Lexmark verkauft **dieselbe Hardware** unter Vertragsnamen, die der Crawler gar
nicht kennt (die Hersteller-Website listet nur die Consumer-Namen CX/MX/CS/MS):

| Vertrags-Modell (Flotte) | Consumer-Pendant (Crawler) | gemeinsame Plattform |
|---|---|---|
| XC4342, XC4352 | CX735adse | `CXTMM` |
| XC4140, XC4150 | CX725 | `CXTAT` |
| XC4240 | CX625adhe | `CXTZJ` |
| M3350 | MS632dwe | `MSTSN` |
| XM5365, XM5370, XM7355 | MX722adhe | `MXTGW` |
| XC9525, XC9535 | CX962se | `CXTLS` |

## Die Lösung — drei Match-Ebenen (`match_method`)

`vw_device_supplies` liefert je `(Gerät, Teilenummer)` genau eine Zeile, markiert
mit dem **sichersten** verwendeten Verfahren (`DISTINCT ON` + Priorität):

| `match_method` | Logik | Wirkung |
|---|---|---|
| `exact` | `model_display = printer_model` | trägt HP unverändert (99,9 %) |
| `model_key` | normalisierter Schlüssel `[a-z]{1,3}[0-9]{2,6}` (`"cx735"`), herstellergeprüft | schält Serie/Plattform ab → Lexmark **0 % → 60 %** |
| `platform` | Lexmark-Firmware-Plattform (`CXTMM.250.217` → `CXTMM`); Vertrags-Modell erbt die Supplies des **einzigen** abgedeckten Consumer-Modells derselben Plattform | Lexmark **60 % → 92 %** |

Zwei IMMUTABLE-Hilfsfunktionen:

- `insights.printer_model_key(text)` — erste Folge *1-3 Buchstaben + 2-6 Ziffern*,
  case-insensitiv. NULL bei ziffern-ersten Modellen (z. B. HP 4102) → die laufen
  weiter rein über `exact`.
- `insights.printer_platform_code(text)` — Suffix-Muster `[A-Z]{4,6}\.[0-9]{3}\.[0-9]{3}`.
  NULL bei allen Nicht-Lexmark-Modellen → `platform` feuert dort nie.

### Warum der Plattform-Code vertrauenswürdig ist

Der Code (`CXTMM`, `MXTGW`, …) ist **Lexmarks eigene Firmware-Plattform** = die
Toner-Familie. Geräte derselben Plattform teilen sich nachweislich die
Kartuschen — Beispiel `CXTMM`: XC4352 erbt exakt die `71C`/`81C`-Toner, `41X`-Fuser
und `71C0Z50`-Imaging-Unit von CX735adse (die echten CX73x-Verbrauchsmaterialien).

**Sicherung gegen Fehlzuordnung:** Eine Plattform taugt nur als Brücke, wenn auf
ihr **genau ein** abgedecktes Consumer-Modell liegt (`HAVING count(DISTINCT
dev_key) = 1`). Misch-Plattformen mit mehreren Supply-Familien werden übersprungen.

## Verbleibende Lücke (~8 % Lexmark, 74 Geräte live)

Vertrags-Modelle auf Plattformen **ohne** abgedecktes Consumer-Pendant in unserer
Flotte: `C4342`/`C4352` (`CSTMM`), `M3250` (`MSTGM`), `C2326` (`CSLBN`),
`XM3142` (`MXTCT`) u. a. Diese brauchen Crawler-Daten, die der Crawler noch nicht
hat (Color-Single-Function-C-Serie + einzelne Mono-Plattformen). → Folge-Arbeit
crawler-seitig (Aufnahme der fehlenden Consumer-Modelle), siehe
[VBM-Crawler-Anbindung](vbm_crawler_integration.md).

KM (`Konica Minolta`) erscheint hier mit 0 % — **gewollt**: KM-OEM-Soll kommt aus
der Excel-Quelle über `vw_spare_part_events`, nicht über `part_compatibility`.

## Test / Rollback

```sql
-- Abdeckung je Hersteller (live)
SELECT d.manufacturer_canonical,
       count(DISTINCT d.fleetmgmt_device_id) FILTER (
         WHERE EXISTS (SELECT 1 FROM insights.vw_device_supplies s
                       WHERE s.fleetmgmt_device_id = d.fleetmgmt_device_id)) AS abgedeckt,
       count(*) AS gesamt
FROM insights.devices_unified d
WHERE d.device_status = 'live'
GROUP BY 1 ORDER BY 3 DESC;

-- match_method-Verteilung
SELECT match_method, count(DISTINCT fleetmgmt_device_id)
FROM insights.vw_device_supplies
WHERE manufacturer_canonical = 'Lexmark' AND device_status = 'live'
GROUP BY 1;
```

Rollback: `DROP VIEW insights.vw_device_supplies;` +
`DROP FUNCTION insights.printer_model_key(text), insights.printer_platform_code(text);`
(beides additiv, keine bestehende Tabelle/Spalte verändert).
