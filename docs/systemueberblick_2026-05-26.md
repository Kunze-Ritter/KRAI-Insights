# KRAI-Insights — Systemüberblick & Standortbestimmung

*Stand: 26.05.2026 · alle Zahlen live aus der Insights-Datenbank · für die Geschäftsleitung*

---

## 1. Worum geht es

**KRAI-Insights** ist ein eigenständiges Auswertungssystem, das drei vorhandene
(nur lesend angebundene) Quellen zu einer gemeinsamen Analyse-Datenbank verbindet
und daraus **Geld-relevante Erkenntnisse** sichtbar macht: zurückholbare
Garantie, verschwendetes Material, Abrechnungsrisiken, Up-Sell, vorausschauende
Wartung und ein Techniker-Assistent. Bedienung über ein deutschsprachiges
Dashboard und einen Chat-Assistenten.

**Datenbasis (read-only, nichts wird in den Quellen verändert):**
| Quelle | Inhalt |
|---|---|
| FleetMgmt (docuform, MSSQL) | 119 Tabellen, **62 Mio. Zeilen** — Geräte, Zähler, Verbrauchsmaterial-Historie, Alarme |
| Radix (Infominds, REST-API) | Aktuelle Werte, Verträge, Kosten/Material, Tickets |
| KRAI (PostgreSQL) | Fehlercode-Wissensbasis, Modell-Stammdaten |

Datenfrische aktuell: FleetMgmt-Verbrauch 19.05., Radix-Kosten 21.05.,
Seitenzähler 19.05. (nächtlicher Abgleich vorgesehen).

---

## 2. Die Flotte

**11.950 Geräte gesamt**, davon nach echter Aktivität (Datenübertragung ≤ 60 Tage):

| Status | Geräte |
|---|---|
| **live (aktiv)** | **6.403** |
| silent (>60 Tage keine Daten) | 5.102 |
| nie gemeldet / deaktiviert / gelöscht | 445 |

> ⚠️ Wichtig fürs Verständnis: Das Admin-„aktiv"-Flag zeigt ~11.800 — die Flotte
> ist also real nur etwa **halb so aktiv** wie auf dem Papier. Alle Kennzahlen
> beziehen sich auf die **6.403 Live-Geräte**. Über **930 Kunden**.

Live-Geräte nach Hersteller: HP 3.961 · Konica Minolta 1.167 · Lexmark 924 ·
Kyocera 181 · Samsung 39 · Canon 17 · Rest ~115.

---

## 3. Verbrauchsmaterial-Abdeckung (OEM-Sollwerte) — das Fundament

Damit Garantie, Standzeiten und Materialkosten überhaupt bewertbar sind, braucht
jedes Gerät die OEM-Reichweiten seiner Verbrauchsmaterialien. Dieser Datensatz
wurde in den letzten Wochen von ~17 % auf praktisch vollständig gebracht:

| Hersteller | Live | OEM-Abdeckung |
|---|---|---|
| HP | 3.961 | **100 %** |
| Lexmark | 924 | **100 %** |
| Kyocera | 181 | **99 %** (nur 1 Modell offen) |
| Konica Minolta | 1.167 | **100 %** (über KM-Datenquelle) |

**→ 97 % aller Live-Geräte (6.228 / 6.403) haben jetzt belastbare OEM-Daten.**
Quelle: ein eigener Hersteller-Crawler (Lexmark/HP/Kyocera, in Seeds versioniert,
per Knopfdruck aktualisierbar) plus die KM-Reichweiten-Liste.

---

## 4. Wo Geld liegt (die Kern-Auswertungen)

### a) Garantie-Reklamation — *seriös bereinigt*
**574 reklamierbare Garantiefälle** (Toner unter 70 % der Soll-Reichweite,
innerhalb Garantiezeit, **nur tatsächlich (fast) leere** Kartuschen, nur
**belastbarer** Hersteller-Soll = Konfidenz hoch/mittel), durchschnittlich nur ~29 %
der Soll-Menge geliefert. **Geschätzt ~27.100 € erstattbar** (Spanne 7.600–89.700 €,
Restwert-Modell). + 24 weitere Fälle mit unsicherer OEM-Referenz (separat, manuell).

> Sprung von 488 → 574 durch den OEM-Soll-Backfill (Migration 062): Die Garantie-
> Bewertung „sah" vorher nur 14 % der Tonerwechsel (alte Radix-Soll-Quelle). Mit den
> Crawler/KM-Reichweiten deckt sie jetzt ~85 % ab — +84 echte, belastbare Fälle, die
> vorher mangels OEM-Referenz unsichtbar waren. Rauschige Referenzen sind als
> „niedrig" getiert (nicht in der Headline).

| Hersteller | Fälle | erstattbar (€) |
|---|---|---|
| Lexmark | 172 (113 serial-belegt) | ~9.570 |
| Konica Minolta | 245 | ~8.990 |
| HP | 51 (24 serial) | ~2.580 |
| Kyocera / Samsung | 20 | ~1.250 |

> Hinweis Glaubwürdigkeit: Diese Zahl war früher ~6× höher — bis wir entdeckten,
> dass halbvoll gewechselte Kartuschen fälschlich als Garantiefall zählten. Jetzt
> zählt nur, was wirklich leer war = **belastbar gegenüber dem Hersteller**.

### b) Toner-Verschwendung — *neue Erkenntnis*
Aus demselben Befund: Kunden werfen **halbvolle Kartuschen weg**.
**~27.300 € weggeworfener Toner** (≈ 1.200 vorzeitige Tausche).
→ Eigene Beratungs-/Abrechnungs-Quelle (Aktionsliste je Kunde im Dashboard).

### c) Up-Sell & Abrechnungsrisiko
- **305 aktive Geräte ohne laufenden Vertrag** → Vertrags-Chance.
- **498 Geräte unter Vertrag, die keine Daten mehr melden** → Abrechnung läuft
  auf Schätz-Zählern (Risiko in beide Richtungen).
- 11.244 Verträge erfasst; ~488.500 € Material aus 88.000 Kosten-Positionen.

### e) Wettbewerbs-Radar („Spionage") — *neue Markt-Intelligenz*
Bleibt der Flotten-Agent (DCA) nach Vertragsende auf dem Kundenserver, melden sich
dort weiter alle Geräte — auch **neue Konkurrenzgeräte**, die der Kunde aufstellt.
**173 Fremdgeräte** (melden live, nicht in unserem Service), davon **23 Konkurrenz-
marken (22 neu)** — z. B. Brother @ Wobak Konstanz, Sharp @ Weingut Schloss Ortenberg,
Canon @ Stadt Konstanz. = Wettbewerbs-Intel + Win-Back-Signal (oder Agent deinstallieren).

### d) Lizenz-Verschwendung (CSP) — *neuer Kostenhebel*
CSP nimmt Geräte automatisch unter Lizenz, auch abgebaute/ersetzte → laufende
Gebühr ohne Gegenwert. **5.412 lizenzierte, aber inaktive Geräte** (von 11.815) —
davon **2.515 „hoch"** (nie gemeldet / > 1 Jahr still und nicht in Radix / Phantom)
= fast sichere Delisting-Kandidaten. **Direkte Ersparnis = Anzahl × Lizenzgebühr/Gerät.**
Liste mit Begründung im Dashboard (Datenqualität) + Assistent.

---

## 5. Service & vorausschauende Wartung

- **Standzeit-/Yield-Bild:** jetzt **1.603 Modell/Farbe-Kombinationen** (vorher nur
  ~53) — durch den OEM-Soll-Backfill (Migration 062) deckt die Standzeit-Bewertung
  ~85 % der Tonerwechsel ab statt 14 %. Grundlage für Kalkulation und Reklamation.
- **Ersatzteil-Frühausfälle:** 204 seiten-belegte Fälle (Trommel/Fixierer/Walze
  unter Soll) — Reklamations- und Qualitätssignal.
- **Verbrauchsmaterial in 14 Tagen fällig:** 607 (proaktive Lieferung).
- **Resttonerbehälter-Vorhersage:** 61 fällig + 63 bald — *über den Seitenzähler*,
  weil die Geräte den Behälter-Füllstand schlecht messen (siehe Loch P3).
- **71 Problem-Geräte** (auffällig viele Alarme / Sensor-Spam) für den Field-Service.
- **Techniker-Assistent:** 2.937 Fehlercodes, davon 1.025 mit Lösungstext.

---

## 6. Datenqualität & offene Löcher (ehrlich, priorisiert)

### 🔴 P1 — strategisch / direktes Geld
1. **Profitabilität pro Gerät fehlt.** Die Klickpreise (Umsatzseite) stehen in
   *keinem* angebundenen System (FleetMgmt-Felder leer, Radix-Service-API ohne
   Preise). Ohne sie keine echte Deckungsbeitrags-/Rentabilitätsrechnung je Gerät.
   → Lösung: Klickpreis-Tabelle vom Vertrieb (oder offizielle Radix-Core-API).
2. **972 Kunden-/Standort-Abweichungen** zwischen FleetMgmt und Radix (608 davon
   auch andere Stadt). Risiko: **Toner-Fehlversand** und Falschabrechnung. Liste
   liegt vor, muss aber **operativ durchgegangen / bereinigt** werden.

### 🟠 P2 — Datenqualität / Abdeckung
3. **498 Geräte „still unter Vertrag"** → Abrechnung auf Schätzzählern.
4. ~~**99 Live-Geräte ohne Hersteller/Modell**~~ ✅ **GEKLÄRT** (Migration 061): Das
   waren überwiegend **Print-Server-Queue-Artefakte** — Druck-Warteschlangen eines
   zentralen Print-Servers, die der Agent als identitätslose „Geräte" mitzählt (Queue-
   Name im IP-Feld). Flotten-weit 414 markiert (`is_queue_artifact`) und aus Live-/
   Lizenz-Zahlen herausgerechnet; je Kunde sichtbar in `vw_print_server_kunden`. Es
   bleiben **174 echte Geräte ohne Radix-Zuordnung** (Marke aus Modellname/Radix nachziehen).
5. ~~Zwei getrennte Abdeckungs-Pfade nicht vereint (KM erschien fälschlich 0 %).~~
   ✅ **BEHOBEN** (Migration 056): vereinheitlichte Abdeckungs-Sicht über beide
   Pfade + Dashboard-Kennzahl „OEM-Abdeckung 97 %".

### 🟡 P3 — bekannt, mit Workaround
6. **Garantie-€ beruht auf nur ~65 Tonerpreisen** (breite Spanne) — mit
   artikelgenauen Einkaufspreisen deutlich schärfer.
7. **Resttonerbehälter-Sensor unzuverlässig** bei Lexmark XC/CX, HP E87xx,
   Kyocera-Color (52 % der Meldungen sind Rauschen). Workaround aktiv:
   Vorhersage über den Seitenzähler; für diese Modelle nur feste Liefer-Kadenz.
8. **5.102 „stille" Geräte** (>60 Tage keine Daten) = Blindstellen für Wartung
   und Garantie. Teils abgebaut/offline — sollte aber bereinigt/geklärt werden.
9. **Kyocera 1 Modell (402ci)** offen; einige **fremde Radix-Geräte** gehören in
   die KRAI-Parts-Datenbank, nicht nach Insights (Zuständigkeit geklärt).
11. **Konica-Minolta-Toner-Soll für Garantie/Yield noch offen** (~3.000 Events):
    Der OEM-Soll-Backfill (Migration 062) deckt HP/Lexmark/Kyocera ab; KM hat keine
    per-Modell-Kompatibilität (Excel-Pfad) → braucht eine bizhub→KM-Modellfamilie-
    Brücke. Folgeschritt.

### 🔒 Sicherheit (vor breitem Rollout)
10. **Dashboard ohne Anmeldung** (nur im Docker-/Dev-Netz). Vor dem Ausrollen an
    Mitarbeiter absichern (Authentifizierung).

---

## 7. Technischer Stand

- **62 Datenbank-Migrationen** angewendet (versioniert, idempotent, zurückbaubar).
- **26 automatisierte Tests grün**, Code-Linting sauber.
- Hersteller-Crawler in eigenem Repo (Daten in versionierten Seeds — gehen nie
  verloren, per `npm run refresh` aktualisierbar).
- Dashboard (Streamlit, 8 Seiten) + Chat-Assistent (32 deterministische
  Auswertungs-Routen, lokales KI-Modell).
- Quellen strikt read-only, DSGVO-konform (keine Kunden-Kontaktdaten/E-Mails;
  Techniker-Wissen aus Tickets bleibt erhalten, Kundennamen pseudonymisiert).

---

## 8. Empfehlung — nächste Schritte (Geschäftswert-sortiert)

1. **Klickpreise beschaffen** → schaltet die Rentabilitäts-/Deckungsbeitrags-
   Auswertung frei (größter offener Hebel).
2. **Die 972 Kunden-Abweichungen abarbeiten** → stoppt Fehlversand/Falschabrechnung.
3. **Garantie- + Toner-Verschwendungs-Listen aktiv nutzen** (~50.000 € Potenzial
   p. a. greifbar) und in einen automatischen Report/Nightly überführen.
4. **Datenqualität:** stille Geräte klären, Hersteller-/Radix-Lücken schließen.
5. **Vor Mitarbeiter-Rollout:** Dashboard absichern.

*Fazit: Das Fundament steht (97 % Material-Abdeckung, saubere & glaubwürdige
Geld-Kennzahlen, vorausschauende Wartung). Der größte verbleibende Hebel ist die
Umsatzseite (Klickpreise) für echte Profitabilität — der Rest sind benannte,
abarbeitbare Datenqualitäts-Punkte.*
