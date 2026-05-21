# FleetMgmt Data Insights — Was steckt wirklich drin?

> Auswertung der **vollständig importierten** Fleet-Management-Datenbank `DevFleetMgmt`
> (Microsoft SQL Server, Container `krai-fleetmgmt-mssql`).
>
> **Stand:** 2026-05-21 · **Datenstand:** 2026-05-19 (letzter Transfer)
> **Volumen:** 119 Tabellen · 62.000.142 Rows · 26 GB live · 2,09 GB komprimiertes Backup
>
> Alle reproduzierbaren SQL-Queries: [`docs/fleetmgmt_analysis_queries.sql`](fleetmgmt_analysis_queries.sql)
> Strategische Übersicht / Tier-Klassifikation: [`docs/fleetmgmt_analysis.md`](fleetmgmt_analysis.md)

---

## TL;DR — Die 8 wichtigsten Erkenntnisse

1. **11.815 aktive Geräte** in 991 Kunden, 11 Jahre Historie (2015–2026).
2. **HP dominiert** mit 44 % der Geräte, gefolgt von Konica Minolta (17 %), Lexmark (13 %), Samsung (8 %), Kyocera (6 %).
3. **Top-Modell:** HP LaserJet E40040 (1.089 Geräte) — gefolgt von HP Color LaserJet MFP X58045 (391) und Samsung M332x (326).
4. **Druckvolumen:** ~11 Mio Seiten / Monat fleet-weit, ~65 % BW / ~35 % Color. Sogar **~8–10 k Fax-Seiten pro Monat** (öffentliche Verwaltung).
5. **Top-Kunden:** Stadt Freiburg (960 Geräte), Stadt Konstanz (906), BruderhausDiakonie Reutlingen (732), Rolls-Royce FN (318), Stadt Villingen (302). Regional klar Süddeutschland / Schwarzwald.
6. **Service-Historie:** 836 k Events über 11 Jahre, davon **44.315 noch offen**. Häufigste Probleme: Yellow-Cartridge-low (sehr viele Modelle), KM-Wasttoner, "Wartungskit austauschen".
7. **Problemmodelle** (Events/Gerät, 90 Tage): HP Color LaserJet Flow **X58045 (47,2)**, KM bizhub C650i (45,6), KM C551i (37,2), HP E87650 (34,8). Diese Modelle sind die "Service-Magnete".
8. **Toner-Realität schlägt OEM-Spec massiv:** Echte Standzeiten liegen typischerweise **10–35 % über** den OEM-Angaben, in Einzelfällen (X58045 Black) bei **+158 %**. Hier liegt **direktes Geld**: Verträge mit OEM-Yield kalkulieren bedeutet automatisch Marge auf Verbrauchsmaterial.

---

## 1. Geräte-Inventar

### 1.1 Bestand

| Metrik | Wert |
|---|---:|
| Devices total | 11.950 |
| **Active** (nicht deaktiviert, nicht gelöscht) | **11.815** |
| Deactivated | 34 |
| Deleted | 101 |

### 1.2 Hersteller-Verteilung (aktive Geräte)

| Vendor | Devices | Anteil |
|---|---:|---:|
| **HP** | **5.216** | 44,1 % |
| **Konica Minolta** | **1.981** | 16,8 % |
| **Lexmark** | **1.592** | 13,5 % |
| Samsung | 983 | 8,3 % |
| Kyocera | 765 | 6,5 % |
| _NULL (unbekannt)_ | 609 | 5,2 % |
| Brother | 155 | 1,3 % |
| Zebra | 131 | 1,1 % |
| Epson | 111 | 0,9 % |
| Canon | 74 | 0,6 % |
| Xerox | 70 | 0,6 % |
| Ricoh | 39 | 0,3 % |
| Toshiba | 24 | 0,2 % |
| Okidata, Sharp, Oce, EFI, TSC, Dell, Honeywell | 60 | 0,5 % |

> **Top 3 = 75 %** der Flotte — der Long-Tail aus 17 weiteren Vendors ist nur 5–10 % der Geräte.

### 1.3 Top-Modelle (aktive Geräte, Top 15)

| Modell | Devices |
|---|---:|
| HP LaserJet E40040 | 1.089 |
| HP Color LaserJet MFP X58045 | 391 |
| Samsung M332x 382x 402x Series | 326 |
| HP LaserJet E50145 | 322 |
| HP LaserJet MFP E52645 | 252 |
| Konica Minolta bizhub C450i | 250 |
| HP Color LaserJet Flow E87740 | 224 |
| HP Color LaserJet Flow E87750 | 218 |
| HP Color LaserJet Flow X58045 | 210 |
| HP PageWide Color MFP E77660 | 190 |
| HP Color LaserJet Flow E87770 | 178 |
| KM bizhub C250i | 176 |
| Samsung X4300 Series | 173 |
| KM bizhub C4050i | 172 |
| HP Color LaserJet Flow E87760 | 166 |

### 1.4 Bestandsentwicklung (Devices pro Jahr eingebucht)

| Jahr | Devices | Trend |
|---|---:|---|
| 2014 | 7 | Start |
| 2015 | 217 | |
| 2016 | 166 | |
| 2017 | 818 | erstes Wachstum |
| 2018 | 435 | |
| 2019 | 725 | |
| 2020 | 464 | Covid-Delle |
| 2021 | 1.034 | |
| 2022 | 946 | |
| **2023** | **2.616** | **Peak (HP-Großdeal?)** |
| 2024 | 1.965 | |
| 2025 | 1.856 | |
| 2026 | 566 | (YTD bis Mai) |

> Klarer Wachstumssprung 2023 — wahrscheinlich Mass-Rollout (E40040 / X58045-Familie).

### 1.5 Lifetime Page Count (aktive Geräte mit Counter)

| Bucket | Devices | Ø Pages |
|---|---:|---:|
| 0–10 K (neu) | 2.228 | 4.232 |
| 10 K – 100 K | 3.265 | 37.898 |
| 100 K – 500 K | 1.086 | 207.197 |
| 500 K – 1 M | 122 | 684.139 |
| 1 M – 5 M | 36 | 1.680.534 |
| **5 M+** | **1** | **9.108.153** |

> Single Top-Volume-Device: **KM bizhub PRESS 1250** (Production Press, 9,1 Mio Pages).

### 1.6 Top 5 High-Volume Geräte

| Modell | Serial | PageCount | Erstdaten |
|---|---|---:|---|
| KM bizhub PRESS 1250 | A4EU021040129 | 9.108.153 | 2025-11-19 |
| KM AccurioPress 6136P | A9JW021000428 | 3.532.023 | 2025-11-12 |
| KM bizhub C754e | A2X0027004025 | 3.341.991 | 2019-04-11 |
| KM bizhub C750i | ACKN021002494 | 3.185.747 | 2022-09-06 |
| KM bizhub 758 | A795021002529 | 2.881.254 | 2018-10-11 |

---

## 2. Kunden

### 2.1 Stammdaten

| Metrik | Wert |
|---|---:|
| Users (Kunden + Contacts) | 991 |
| Mit Email | 565 (57 %) |
| Mit Adresse / City | 860 (87 %) |
| Locked Accounts | 1 |

### 2.2 Geografie (Top 10 Städte)

| Stadt | Users |
|---|---:|
| **Freiburg** | **103** |
| Villingen-Schwenningen | 32 |
| Titisee-Neustadt | 26 |
| Emmendingen | 25 |
| Villingen | 23 |
| Waldkirch | 22 |
| Freiburg im Breisgau | 14 |
| Bad Krozingen / Denzlingen / Donaueschingen | je 13 |
| Lenzkirch | 11 |
| Hinterzarten / Konstanz / Trossingen / VS | je 10 |

> **Eindeutig:** Klassischer regionaler MPS-Provider Schwarzwald / Bodensee / Süd-Baden.

### 2.3 Top-Kunden nach Gerätezahl (Top 15)

| Kunde | Stadt | Devices |
|---|---|---:|
| Stadt_Freiburg | Freiburg | **960** |
| Stadt_Konstanz | Konstanz | **906** |
| BruderhausDiakonie | Reutlingen | 732 |
| Rolls-Royce | Friedrichshafen | 318 |
| Stadt_Villingen | Villingen-Schwenningen | 302 |
| Dunkermotoren | — | 213 |
| Sparkasse_SWB | Villingen | 213 |
| Sparkasse_Bodensee | Friedrichshafen | 190 |
| Sparkasse_Hegau_Bodensee | Singen | 183 |
| Ernst_und_Koenig | Freiburg | 182 |
| Landratsamt | Esslingen | 181 |
| IMS_Gear | Donaueschingen | 152 |
| METZ CONNECT | Blumberg | 148 |
| Friedrich Scharr KG | Stuttgart-Vaihingen | 147 |
| Allweiler GmbH | Radolfzell | 146 |

> **Drei Stadtverwaltungen + drei Sparkassen + ein Großkonzern (Rolls-Royce)** = stabile, lange Vertragslaufzeiten zu erwarten.

### 2.4 Top-Kunden nach Volumen (12 Monate, ab 2025-05)

| Kunde | Pages 12 mo |
|---|---:|
| Landratsamt Esslingen Schulen | 9.758.848 |
| Stadt_Konstanz | 8.451.888 |
| Landratsamt Esslingen | 7.872.003 |
| Stadt_Freiburg | 7.575.010 |
| BruderhausDiakonie | 4.893.497 |
| Landratsamt Ortenau | 3.059.816 |
| Ernst_und_Koenig | 2.418.249 |
| Schulen Schwenningen | 2.165.042 |
| Sparkasse_Hegau_Bodensee | 2.066.996 |
| Rolls-Royce | 2.006.020 |

> Schulen drucken viel — Landratsamt Esslingen Schulen ist mit 9,76 Mio Seiten / 12 Monaten Volumen-Champion.

---

## 3. Druckvolumen (letzte 12 Monate)

| Monat (YYYYMM) | Active Devices | Total Pages | BW | Color | Copies | Scans | Faxes |
|---|---:|---:|---:|---:|---:|---:|---:|
| **202604** | **11.897** | **11.007.970** | 7.173.274 | 3.834.696 | 1.133.009 | 2.361.024 | 8.213 |
| 202603 | 11.594 | 12.740.949 | 8.241.119 | 4.499.830 | 1.397.570 | 2.832.771 | 9.873 |
| 202602 | 11.388 | 10.467.171 | 6.690.875 | 3.776.296 | 1.022.233 | 2.050.136 | 8.213 |
| 202601 | 11.259 | 11.294.583 | 7.376.186 | 3.918.397 | 1.278.152 | 2.310.533 | 8.826 |
| 202512 | 11.158 | 9.536.798 | 6.225.898 | 3.310.900 | 1.023.646 | 2.132.640 | 7.829 |
| 202511 | 10.814 | 10.890.295 | 7.026.930 | 3.863.365 | 1.356.274 | 2.119.827 | 9.452 |
| 202510 | 10.331 | 10.927.747 | 7.055.429 | 3.872.318 | 1.214.992 | 2.302.995 | 9.193 |
| 202509 | 10.181 | 9.821.261 | 6.326.675 | 3.494.586 | 1.086.054 | 2.051.908 | 9.029 |
| 202508 | 10.101 | 6.399.807 | 4.375.194 | 2.024.613 | 446.596 | 1.864.835 | 8.525 |
| 202507 | 9.968 | 10.361.708 | 6.792.218 | 3.569.490 | 1.039.102 | 2.451.375 | 10.062 |
| 202506 | 9.771 | 7.815.480 | 5.193.153 | 2.622.327 | 805.360 | 1.886.574 | 9.047 |
| 202505 | 9.623 | 9.338.196 | 6.234.062 | 3.104.134 | 1.141.302 | 2.123.273 | 6.284 |

**Beobachtungen:**

- **Stetiges Wachstum:** Aktive Geräte +24 % in 12 Monaten (9.623 → 11.897).
- **Saisonalität:** August-Delle (Sommerferien Schulen!) sehr deutlich (Total ~6,4 M vs. März-Peak 12,7 M).
- **Color-Anteil:** ~35 % stabil — kein Cost-Saving-Trend Richtung BW.
- **Faxes** sind im **Aufwärtstrend** statt zu verschwinden — typisch für Behörden / Gesundheitswesen.

---

## 4. Service & Events

### 4.1 Übersicht

| Metrik | Wert |
|---|---:|
| Events total | **836.185** |
| Davon noch offen | 44.315 |
| Davon geschlossen | 791.870 |
| Ältester Event | 2015-11-23 |
| Neuester Event | 2026-05-19 |

### 4.2 Severity-Verteilung

| Severity | Count |
|---:|---:|
| 4 (Info / Notification) | 484.488 |
| 1 (Critical) | 313.191 |
| 3 | 30.051 |
| 2 | 8.455 |

### 4.3 Top 10 Alert-Codes mit Beschreibung

| AlertCode | sKey | Occurrences | Devices | Beschreibung |
|---:|---|---:|---:|---|
| 0 | _NULL_ | 392.676 | — | _Wasttoner KM C654e_C754e_ |
| 13 | 0 | 177.670 | — | Wartungskit austauschen. Empf. Lebensdauer überschritten |
| 1 | _NULL_ | 44.395 | — | Vorrichtung Ausfall (44–942) |
| 0 | PrMibMarker.01 | 20.174 | — | yellow ink HP L0S31YC bei Füllstand niedrig |
| 1104 | 1 | 16.381 | — | Yellow Cartridge **low** |
| 1101 | 0 | 14.195 | — | Yellow Cartridge **very low** |
| 13 | -2 | 14.080 | — | Yellow Drum **very low** |
| 0 | PrMibMarker.04 | 12.747 | — | Yellow Ink Supply Unit T11C4 |
| 1101 | -2 | 11.236 | — | Yellow Cartridge very low |
| 1107 | -2 | 7.486 | — | Wastetoner near full |

> **Auffällig:** "Yellow" / Gelb dominiert die Alerts. Das ist typisch — Gelb wird am wenigsten gedruckt, also bleibt es länger im Gerät und wird am häufigsten als "alt / niedrig" gemeldet.

### 4.4 Problem-Modelle nach Events/Gerät (letzte 90 Tage)

| Modell | Events 90 d | Devices | Events / Device |
|---|---:|---:|---:|
| **HP Color LaserJet Flow X58045** | 6.092 | 129 | **47,2** |
| KM bizhub C650i | 228 | 5 | 45,6 |
| KM bizhub C551i | 223 | 6 | 37,2 |
| HP Color LaserJet Flow E87650 | 174 | 5 | 34,8 |
| HP LaserJet MFP E42540 | 1.348 | 53 | 25,4 |
| KM bizhub C4050i | 2.579 | 105 | 24,6 |
| HP Color LaserJet Flow E87640 | 358 | 15 | 23,9 |
| KM bizhub C550i | 139 | 6 | 23,2 |
| HP LaserJet MFP E52645 | 4.223 | 183 | 23,1 |
| KM bizhub C224e | 115 | 5 | 23,0 |
| KM bizhub C3351i | 339 | 17 | 19,9 |
| HP Color LaserJet MFP X58045 | 4.549 | 287 | 15,9 |

> **Top-1 Problemkind:** HP Color LaserJet **Flow X58045** mit ~47 Events / Gerät in 90 Tagen (durchschnittlich ~1 Event pro 2 Tage und Gerät!). Hier lohnt sich entweder eine Service-Pauschale-Anpassung oder ein Modellwechsel.

### 4.5 Top-Problem-Devices (Einzelgeräte, 90 Tage)

| Modell | Serial | Events 90 d |
|---|---|---:|
| Samsung C406x Series | 0CA0BJEJ900009J | **20.732** |
| HP Color LaserJet Flow X58045 | CZBBS620VH | 5.296 |
| KM bizhub C4050i | AAJN021201615 | 685 |
| Lexmark CX625adhe | 752912924DDPF | 601 |
| Lexmark CX625adhe | 752912924DF02 | 546 |

> Ein einzelnes Samsung-Gerät hat **20.732 Events** in 90 Tagen → spammt Loops, Sensor defekt oder Netzwerkproblem. **Top-Kandidat für sofortigen Field-Service-Check.**

---

## 5. Verbrauchsmaterial — Realität schlägt OEM-Spec

### 5.1 Toner-Refill-Übersicht

| Metrik | Wert |
|---|---:|
| Toner-Refill-Events | **199.170** |
| Geräte | 6.736 |
| Ältester Refill | 2015-11-23 |
| Neuester Refill | 2026-05-19 |

### 5.2 Realität pro Farbe (über alle Modelle)

| Farbe | Refills | Devices | Ø Seiten / Tonereinheit | Ø Coverage |
|---|---:|---:|---:|---:|
| **Black** | 12.722 | 2.764 | **29.308** | 14,47 % |
| _NULL/legacy_ | 4.523 | 730 | 45.273 | 7,26 % |
| Yellow | 3.084 | 932 | 44.828 | 17,07 % |
| Cyan | 2.813 | 887 | 46.496 | 15,69 % |
| Magenta | 2.585 | 829 | 48.243 | 18,48 % |

> **Hinweis:** Coverage = bedruckte Fläche pro Seite. OEM-Hersteller rechnen meist mit **5 %** Standard-Coverage (ISO/IEC 19752).
> **Realität liegt bei 14–18 %** — d.h. die tatsächliche Coverage ist **3× höher** als die OEM-Annahme. Das bedeutet: theoretische Yield-Werte (laut OEM) sind in der Praxis **niedriger** zu erwarten — und Reality-Daten sind nötig für realistische Kalkulationen.

### 5.3 Black-Toner-Lebensdauer pro Modell (REAL vs. OEM-TARGET)

| Modell | Refills | Ø Pages REAL | OEM Target | **% von OEM** |
|---|---:|---:|---:|---:|
| HP LaserJet E40040 | 1.008 | 10.453 | 10.000 | **104,5 %** |
| KM bizhub C450i | 994 | 33.759 | 28.000 | **120,6 %** |
| HP PageWide MFP E77660 | 702 | 21.492 | _NULL_ | — |
| KM bizhub C4050i | 425 | 13.676 | 13.000 | 105,2 % |
| KM bizhub C458 | 403 | 44.937 | 34.643 | **129,7 %** |
| HP LJ Flow E87770 | 374 | 58.507 | 50.000 | **117,0 %** |
| HP Color LJ E55040 | 311 | 10.986 | 14.900 | 73,7 % |
| KM bizhub C3350i | 270 | 13.994 | 10.000 | **139,9 %** |
| HP LJ Flow E87760 | 263 | 66.899 | 50.000 | **133,8 %** |
| HP Color LJ MFP E87740 | 252 | 54.986 | 50.000 | 110,0 % |
| KM bizhub C250i | 242 | 26.920 | 28.000 | 96,1 % |
| HP Color LJ MFP E57540 | 210 | 12.159 | 14.900 | 81,6 % |
| KM bizhub C258 | 209 | 28.155 | 29.186 | 96,5 % |
| **HP Color LJ MFP X58045** | **188** | **16.655** | **6.469** | **257,5 % 🚀** |
| HP LJ Flow E87740 | 175 | 61.301 | 50.000 | 122,6 % |

> **Drei Erkenntnisse:**
>
> 1. **Die meisten Modelle übertreffen ihre OEM-Specs um 10–35 %.** Das ist Geld, das bei OEM-basierter Kalkulation komplett auf die Marge fällt.
> 2. **HP Color LJ MFP X58045** schreibt sich aus dem OEM-Target raus (158 % darüber) — vermutlich ist die "Slipstream"-Cartridge mit 6 469 nominal-Pages der Eintragstest, aber die HighYield-Variante hat tatsächlich ~16 k Pages.
> 3. **HP Color LJ E55040 / E57540** liegen unter 100 % → Anwender mit hoher Coverage, oder kürzere Standzeit bedingt durch das Modell.

### 5.4 Color-Cartridges nach Modell (Top 10)

| Modell | Color | Refills | Ø Pages REAL | Ø Coverage |
|---|---|---:|---:|---:|
| KM bizhub C450i | yellow | 332 | 54.314 | 10,50 % |
| HP PageWide MFP E77660 | yellow | 325 | 38.979 | — |
| HP PageWide MFP E77660 | cyan | 281 | 42.984 | — |
| KM bizhub C450i | cyan | 250 | 63.016 | 7,00 % |
| HP PageWide MFP E77660 | magenta | 220 | 51.947 | — |
| KM bizhub C450i | magenta | 193 | 75.135 | 7,78 % |
| HP Color LJ E55040 | yellow | 167 | 17.361 | 6,47 % |
| HP Color LJ E55040 | cyan | 156 | 18.401 | 6,14 % |
| HP Color LJ E55040 | magenta | 152 | 18.925 | 5,94 % |
| KM bizhub C4050i | cyan | 136 | 17.186 | 14,09 % |

> Color-Coverage typischerweise **5–18 %**, deutlich unter Black-Coverage. Das passt zu klassischem Office-Print (Schwarz dominant, Color für Hervorhebungen).

### 5.5 Wartungs-Reminder

| Wartungstyp | Aktiv auf Devices |
|---|---:|
| Wasttoner KM C224e/C284e/C364e/C454e/C554e | 268 |
| Wasttoner KM C4050i | 137 |
| Wasttoner KM C3350 | 15 |
| Samsung X4250/X4300 | 11 |
| Wasttoner KM 758 | 5 |
| Wasttoner HP E87640 | 4 |
| Wasttoner KM C654e/C754e | 3 |

> Insgesamt nur **448 Reminders** auf 430 Geräten — Wartungsregeln sind extrem KM-zentriert (Wastetoner-Bins).

### 5.6 Spare-Parts-Katalog (ACCMARKERCOVERAGE)

| Hersteller | Parts | Ø Yield (Seiten) |
|---|---:|---:|
| **HP** | 2.577 | 60.573 |
| **Konica Minolta** | 1.615 | 208.969 |
| Lexmark | 1.597 | 78.021 |
| Kyocera | 782 | 16.795 |
| Brother | 487 | 24.065 |
| Samsung | 315 | 83.692 |
| Epson | 287 | 8.905 |
| Xerox | 253 | 53.255 |
| Canon | 216 | 33.790 |
| Ricoh | 171 | 20.634 |
| Sharp | 114 | 171.990 |
| Okidata, Dell, Oce, Toshiba | 113 | divers |

> **20.525 Spare-Parts** insgesamt von **16 Herstellern** — ein wertvoller normalisierter Parts-Katalog, der unabhängig vom Service-Workflow als Referenz für KRAI dienen kann (z. B. Mapping `partNo ↔ Lifespan ↔ Manufacturer`). **Preise sind nicht hinterlegt** (alle NULL).

---

## 6. 11-Jahres-Zeitreihen — SNMP & Counter

### 6.1 Datenmenge

| Tabelle | Rows | Devices | Zeitraum |
|---|---:|---:|---|
| **ACCSNMPHISTORY** | **48.074.445** | 10.998 | 2015-09-09 → 2026-05-19 |
| **ACCMIBCOUNTERVALUES** | **12.449.056** | 6.741 | 2015-11-23 → 2026-05-19 |

### 6.2 Wachstum pro Jahr

| Jahr | SNMP-Reads | Counter-Reads | Devices (Counter) |
|---:|---:|---:|---:|
| 2015 | 294 | 21 | 1 |
| 2016 | 14.430 | 3.727 | 13 |
| 2017 | 37.251 | 22.632 | 43 |
| 2018 | 75.560 | 47.629 | 99 |
| 2019 | 243.559 | 138.907 | 243 |
| 2020 | 559.420 | 240.869 | 434 |
| 2021 | 1.418.085 | 512.541 | 980 |
| 2022 | 2.447.636 | 797.808 | 1.653 |
| 2023 | 5.997.978 | 1.956.052 | 3.541 |
| 2024 | 11.593.700 | 3.089.592 | 5.060 |
| 2025 | **16.946.077** | 3.885.792 | 6.128 |
| 2026 | 8.740.455 (YTD) | 1.753.486 (YTD) | 6.369 |

> **Massiver Wachstum**: SNMP-Polling 2015 ~300 Reads → 2025 ~17 Mio Reads. Wird genutzt für Predictive-Modelle (Remaining Pages / Days pro Toner), Verbrauchsverlauf, Slope-Detection.

### 6.3 Was machen wir mit der Zeitreihen-Goldmine?

- **Daily Page-Volume pro Gerät** über 11 Jahre — perfekt für Saisonalitäts-Modelle.
- **Toner-Slope** (`ACCSNMPHISTORY.Slope`) ist bereits berechnet, plus `RemainingPages` und `RemainingDays`. Diese Spalten **alleine** sind Predictive-Maintenance-Output, den man direkt anzeigen oder in Just-In-Time-Logistik einbinden kann.
- **Counter-Trends** (ACCMIBCOUNTERVALUES C1..C50) — die Spalten sind generisch, aber per Device-Modell-Template lassen sich z. B. C1 = TotalCounter, C2 = ColorCounter etc. zuordnen (siehe `ACCMIBCOUNTERDEF` / `ACCMIBCOUNTERTEMPLATE`).
- **Page-per-Day pro Gerät** für TCO-Berechnungen ist über `MAX(C1) by day` trivial verfügbar.

---

## 7. Verträge

| Metrik | Wert |
|---|---:|
| Verträge total | 985 |
| Aktiv markiert | 985 |
| Ausgelaufen (ContractEnd < heute) | 0 |
| Ältester Start | 2014-12-02 |
| Device-Contract-Links | 31.491 |
| Eindeutige Devices mit Vertrag | 7.033 |
| Eindeutige genutzte Verträge | 775 |

> **Beachte:** Verträge tragen Mono/Color **PageCharge**-Spalten (Standard + 2 Optionen) sowie **FreePages**. Aktuell sind allerdings die Top-Tier-Charges leer → Vertragsbedingungen werden vermutlich offline gepflegt oder über `ChargeMonths` / `OrderOpt` referenziert.
>
> 7.033 Geräte mit Vertrag von 11.815 aktiven = **60 % unter Vertrag**, 40 % out-of-contract → klare Chance für Up-Sell.

---

## 8. Was ist nicht oder kaum befüllt?

Aus dem Voll-Import bekannt:

| Daten | Status | Konsequenz |
|---|---|---|
| `WarrantyStart` / `WarrantyMonths` | **Komplett leer** (0 Records) | Warranty-Status muss man aus `Created` + Vendor-Default ableiten |
| `ServiceContract` Flag in ACCDEVICES | Alle 0 oder NULL | Vertragsstatus stattdessen über `ACCDeviceContracts`-Join |
| `Price` in `ACCMARKERCOVERAGE` | Komplett leer | Preise extern / Excel — kein Cost-Tracking aus DB möglich |
| `PageChargeMonoStd` / `PageChargeColorStd` (Top-Tier) | Leer | Charge-Tiers offenbar offline / im OrderOpt referenziert |
| 609 Devices ohne Vendor (`VendorId NULL`) | 5,2 % | Datenqualität — sollte bei Import-Cleanup nachgepflegt werden |

---

## 9. Empfehlung — Wofür ist diese DB nützlich?

### Direkt nutzbar (ohne Mapping in KRAI)

1. **Predictive Maintenance Reality-Layer:** Die `ACCSNMPHISTORY.Slope` / `RemainingPages` / `RemainingDays`-Spalten liefern bereits aussagekräftige Vorhersagen pro Toner — kann als zweite Datenquelle neben KRAI's eigenen Counter-Modellen dienen.
2. **Toner-Standzeit-Benchmark:** Realität-Daten pro Modell × Farbe (siehe Abschnitt 5.3) sind **kommerziell sehr wertvoll** für Vertrags-Kalkulation und Kunden-Reporting.
3. **Problemmodell-Identifikation:** Events/Device-Ratio (Abschnitt 4.4) zeigt direkt, welche Modelle ein Service-Risk sind.
4. **Saisonalitäts-Modell** für Volumen-Prognosen (Abschnitt 3).

### Für spätere KRAI-Integration (per API)

- **Customer-Mapping:** ACCUSERS → krai_users / Manufacturer Account-Hierarchie
- **Device-Inventory:** ACCDEVICES → krai_core.devices (mit Vendor-Mapping HP / Konica Minolta → bestehende KRAI-Manufacturer-IDs)
- **Spare-Parts-Catalog:** ACCMARKERCOVERAGE → krai_parts.parts_catalog (20 k Parts!)
- **Error-Code-History:** ACCEVENTHISTORY.AlertCode / sKey kann gegen krai_intelligence.error_codes gematcht werden — das ist eine **echte Validierungsbasis für KRAI's Error-Code-Extraktion** (836 k reale Service-Events!).

---

## 10. Reproduzierbarkeit

Alle Queries reproduzierbar via:

```bash
docker exec -i krai-fleetmgmt-mssql /opt/mssql-tools18/bin/sqlcmd \
  -S localhost -U sa -P "$env:MSSQL_SA_PASSWORD" -C \
  -d DevFleetMgmt \
  -i /scripts/fleetmgmt_analysis_queries.sql
```

Backup für Disaster-Recovery: `database/fleetmgmt/backups/DevFleetMgmt_20260520.bak` (2,09 GB komprimiert).

---

_Letzte Aktualisierung: 2026-05-21 — Analyse direkt gegen live Docker-Container `krai-fleetmgmt-mssql` durchgeführt._
