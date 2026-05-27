# Garantie & Geld zurückholen

Ziel: defekte Verbrauchsmaterialien (Toner, Trommeln) erkennen, die **vorzeitig
ausgefallen** sind, und den beim Hersteller reklamierbaren Wert beziffern — mit
belastbarem Nachweis.

## 1. Wann ist etwas ein Garantiefall?

Pro Material-Lebenszyklus (eingebaut → gewechselt) bewerten wir **zwei** Achsen:

- **Zeit:** Wie alt war das Teil beim Wechsel? (`age_days`)
- **Gelieferte Tonermenge (deckungskorrigiert):** wie viel der Soll-**Tonermenge**
  hat die Patrone geliefert? (`pct_of_oem`, siehe unten)

**WICHTIG — Deckungskorrektur (5 %).** Das Hersteller-Soll (z. B. 20.000 Seiten)
gilt bei **5 % Deckung** (ISO/IEC 19752). Druckt ein Kunde mit z. B. 8,5 % Deckung,
liefert die Patrone bei **gleicher Tonermenge** weniger Seiten — das ist **kein**
Frühausfall. Wir vergleichen daher nicht Seiten, sondern die gelieferte Tonermenge:

```
pct_of_oem (Toner) = gelaufene Seiten × reale Deckung / (Soll-Seiten × 5 %) × 100
```

Fehlt die reale Deckung (oder ist sie unplausibel >100 %), fällt die Bewertung auf
den rohen Seiten-Wert zurück (`coverage_belegt = false`, schwächerer Nachweis).

Daraus die Einordnung (Sicht `vw_warranty_assessment`):

| Klasse | Bedingung | Bedeutung |
|---|---|---|
| **claim** (Garantiefall) | ≤ 365 Tage **und** < 70 % der Soll-Tonermenge | innerhalb Garantie zu wenig Toner geliefert → reklamieren |
| **negotiation** (Verhandlung) | > 365 Tage **und** < 70 % der Soll-Tonermenge | außerhalb Zeit, aber klar unter Soll → Hebel ggü. Hersteller |
| **wear** (Verschleiß) | ≤ 365 Tage **und** ≥ 70 % geliefert | normal verbraucht, kein Fall |
| **normal** | > 365 Tage **und** ≥ 70 % geliefert | unauffällig |
| **artifact** | < 100 Seiten oder Ein-/Ausbau am selben Tag | Mess-/Logging-Artefakt |
| **fehlmeldung** | Falschmeldung (siehe unten) | kein echter Wechsel |

**Warum 70 %?** Eine Patrone, die deutlich unter ihrer Soll-Tonermenge ausfällt, ist
glaubwürdig defekt. 70 % filtert normale Streuung. **Beispiel:** CAP2435126E2 lief
11.597 Seiten (58 % der Soll-Seiten), aber bei 8,5 % Deckung = **99 % der Soll-
Tonermenge** → KEIN Garantiefall (Vielnutzer, keine Reklamation).

**Effekt der Deckungskorrektur:** Garantiefälle 2.839 → **1.185** (Vielnutzer raus,
echte Niedrig-Deckungs-Ausfälle dazu); davon ~888 mit Deckungsbeleg.

**Warum 1 Jahr?** Standard-Garantiezeit für Verbrauchsmaterial. Per Hersteller
anpassbar.

## 2. Fehlmeldungen herausfiltern (wichtig!)

Die Flotten-Software meldet nicht nur echte Patronenwechsel, sondern auch
**Wiedereinsetzungen** (Tür auf/zu, gleiche Patrone wieder rein, Reset). Diese
erzeugen einen Phantom-„Wechsel" mit oft niedriger Seitenzahl — und sahen früher
wie Garantiefälle aus.

Wir filtern sie über die Patronen-Seriennummer: ist die Seriennummer identisch zur
vorherigen, ist es **kein** echter Wechsel → Klasse `fehlmeldung`, nicht `claim`.

> **Datenfalle (behoben):** Manche Hersteller — v. a. **Konica Minolta** und
> **Kyocera** — melden die Seriennummer als **leeren String `''`** statt NULL.
> Anfangs sah die Logik `'' = ''` bei jedem Wechsel und stufte ALLE als Fehlmeldung
> ein → Konica Minolta hatte fälschlich **0** Garantiefälle. Seit dem Fix wird `''`
> wie „keine Seriennummer" behandelt; die Wiedereinsetzungs-Erkennung greift nur
> noch bei einer echt wiederholten Seriennummer. Wirkung: Fehlmeldungen
> 10.657 → 131, Garantiefälle 1.626 → ~3.174.

## 3. Serial-belegt vs. ohne Seriennummer (Nachweis-Stärke)

- **serial-belegt:** Die Patronen-Seriennummer ist erfasst → stärkster Nachweis für
  die Einreichung (Hersteller kann das Teil eindeutig zuordnen).
- **ohne Seriennummer:** Manche Geräte (Konica Minolta, Kyocera) melden **keine**
  elektronische Seriennummer. Die Fälle sind über die **FleetMgmt-Zähler** belegt
  (gelaufene Seiten vs. Soll), aber ohne Serial — etwas schwächerer Nachweis.

Das Dashboard zeigt daher **„Garantiefälle gesamt"** und **„davon serial-belegt"**.
Beide sind real; die Trennung macht nur die Nachweis-Stärke transparent.

## 4. Was ist der € wert? (Restwert-Modell)

Man bekommt **nicht** den vollen Patronenpreis zurück — nur den **nicht
verbrauchten Anteil**. Wenn eine Patrone 30 % ihrer Soll-Laufleistung erreicht hat,
sind 70 % „verschenkt" und damit erstattbar:

```
erstattbarer Anteil je Fall = 1 − (gelieferte Tonermenge / Soll-Tonermenge)
zentraler €-Wert = Σ (erstattbarer Anteil × Tonerpreis des Herstellers)
Band (Unsicherheit) = Σ (erstattbarer Anteil) × {globaler p10 ; p90}
```

> **Schätzung, bewusst grob — jetzt mit Herstellerpreis + Band (Migration 046).**
> Früher: ein **einziger** globaler Median (~105 €) × Restwert-Summe → „~74.500 €".
> Zwei Probleme: (a) nur **65 Preispunkte**, Streuung 21–247 € (p10–p90) → 12-fache
> Spanne; (b) der globale Median ist **nach oben verzerrt** — die meisten Fälle sind
> Konica Minolta (Toner-Median **55 €**) und Lexmark (~18 €), während teure Toner den
> globalen Median hochziehen. Jetzt wird **je Hersteller** mit dessen eigenem
> Toner-Median bewertet (wo ≥ 5 Preise vorliegen, sonst global) →
> **zentraler Wert ~53.000 €** statt 74.500 €. Zusätzlich wird das **Band**
> (~15.000–175.000 €) ausgewiesen, damit die Unsicherheit sichtbar bleibt.
> **Spalten:** `vw_lagebericht.claim_restwert_eur` (+ `_low`/`_high`),
> `vw_warranty_by_manufacturer.erstattbar_eur` (+ `toner_preis_eur`).
> **Grenze:** Lexmark hat nur **1** Preisbeleg → fällt auf den globalen Median zurück
> und ist damit eher zu hoch angesetzt. Die **Fallzahlen und Laufleistungs-% sind
> dagegen hart belegt.** Eine punktgenaue €-Zahl bräuchte flächendeckende
> Stück-/Artikelpreise (offizielle Core-API).

## 5. Zeitfenster — was ist HEUTE noch einreichbar?

Die Daten reichen über **~9 Jahre** (Garantiefälle ab 2017). Die Gesamtsumme ist
daher **historisch** — ein Fall von 2022 ist beim Hersteller längst aus der Frist.

| Zeitfenster (Wechseldatum) | Fälle | erstattbar (geschätzt) |
|---|---|---|
| letzte 90 Tage | ~187 | ~13.000 € |
| 3–12 Monate | ~520 | ~34.000 € |
| älter als 1 Jahr | ~2.467 | ~189.000 € (vermutlich verfallen) |

**Realistisch einreichbar** ist nur das jüngste Fenster (grob die letzten 12
Monate). Die genaue Frist hängt vom Hersteller ab — deshalb prüfen wir die
**abgeschlossenen Garantiefälle in Radix**, um den tatsächlich akzeptierten
Zeitraum je Hersteller abzuleiten und den „noch einreichbar"-Schnitt sauber zu
setzen.

## 5b. Datenqualität & bekannte Grenzen (Audit 2026-05-23)

- **Seriennummer ist KORREKT (verifiziert 2026-05-23).** Ein anfänglicher
  Off-by-one-Verdacht wurde an einem realen FleetMgmt-Fall widerlegt: Die
  FleetMgmt-Meldung lautet „S/N **X** bei Füllstand 1 % ersetzt. Neue S/N erkannt:
  **Y**" — d. h. `ACCMARKERREFILL.SerialNo` = die **ausgefallene/ersetzte** Patrone
  (X), und `lDiffPageCount` = deren Laufzeit. Beide gehören zur selben Patrone; die
  „neue" Serial (Y) wird korrekt NICHT verwendet. Beispiel: CAP2435126E2 lief
  92.184→103.781 = 11.597 Seiten (58 % von 20.000) → Garantiefall, korrekt mit
  CAP2435126E2 ausgewiesen. **Die serial-belegten Fälle nennen die richtige Patrone.**
- **Same-Day-Artefakte entfernt** (Migration 041): Zyklen mit `age_days = 0` (Ein-
  und Ausbau am selben Tag = simultane Mehrfach-Meldung) zählen als `artifact`.
- **86 % der VBM-Events ohne Hersteller-Soll** → Garantie-Bewertung nur für ~14 %
  möglich; die Garantiefälle stammen aus diesem Teil.
- **€ nur für Toner** (Migration 042): das Rückhol-Potenzial nutzt den Tonerpreis und
  gilt daher nur für Toner-Fälle; CRU-Teile separat (andere Preise).
- **€ herstellergewichtet + Band** (Migration 046): statt eines einzigen globalen
  Medians (verzerrte ~74.500 €) jetzt der **Toner-Median je Hersteller** (zentral
  ~53.000 €) plus ein ausgewiesenes **Unsicherheits-Band** (~15.000–175.000 €, aus
  p10/p90 von nur 65 Preisen). Siehe §4.
- **Ersatzteil-Frühausfälle usage-validiert** (Migration 045): Frühausfall nur bei
  < 70 % einer **Seiten-Referenz** (OEM-Soll oder Vergleichs-Median), nicht mehr rein
  zeitbasiert; Headline zählt belegte **Geräte** (~192) statt Roh-Zeilen (4.077). Siehe §6.
- **Verrauschte Rohdaten** (viele 0-Seiten-Events + Duplikate) — durch `<100 Seiten`
  und `age=0` aus den Garantiefällen herausgehalten.

Regressionstests in `tests/test_warranty_invariants.py` sichern diese Regeln ab.

## 6. Ersatzteile (nicht nur Toner!)

Garantie betrifft **nicht nur Verbrauchsmaterial** (Toner, Resttonerbehälter),
sondern auch **Ersatzteile** (Fixiereinheit, Trommel, Transferband, Walzen,
Mainboards, …). Die Logik ist anders:

- **Verbrauchsmaterial (oben):** hat eine **Soll-Laufleistung** (Seiten) → Frühausfall
  = unter 70 % der Soll. Quelle: FleetMgmt VBM.
- **Ersatzteile:** haben **keine** Soll-Laufleistung, nur eine **~1-Jahres-Garantie**.
  Die reale Standzeit leiten wir aus der **Wiedereinbau-Historie** ab: wird dasselbe
  Teil auf demselben Gerät erneut getauscht, ist das Intervall die Standzeit des
  Vorgängers. Quelle: Radix-Material (`cost_events`).

**Zwei Auswertungen** (`docs` → Sichten `vw_part_*`):

1. **Frühausfälle** (`vw_part_early_failures`): ein Teil ist nur dann ein Frühausfall,
   wenn es **unter 70 % einer Laufleistungs-Referenz (in Seiten)** lief — **nicht**
   schon, weil es innerhalb eines Jahres erneut getauscht wurde. Konfidenz-Stufen:
   - **`hoch`** — unter 70 % des **Hersteller-Soll** (OEM-Nominal, Seiten).
   - **`mittel`** — unter 70 % der **Vergleichs-Laufleistung** gleicher Geräte/Teile
     (Median je Modell ≥ 5, sonst Hersteller ≥ 8, sonst Teiltyp ≥ 20 Stichproben).
   - **`niedrig`** — **kein** Seitenbeleg vorhanden → nur die Zeitheuristik (7–365 Tage).
     Standardmäßig ausgeblendet und **nicht** in der Headline.

   > **Warum die Verschärfung (Audit 2026-05-23, Migration 045).** Die alte Logik
   > stufte **jedes** binnen 7–365 Tagen erneut getauschte Teil als Frühausfall ein —
   > **ohne Seitenprüfung** (genau der Deckungs-/Nutzungsfehler, der bei Toner in 043
   > schon behoben war). Messung: 92 % der 4.077 Zeilen liefen über die reine
   > Zeitheuristik; die 135 davon **mit** Seitendaten liefen im **Median 27.936 Seiten**
   > (p90 143.728; 23 über 100.000) = **Vielnutzer-Normalverschleiß**, fälschlich als
   > Garantie markiert. Zudem massive Mehrfachzählung: 4.077 Zeilen über nur **720**
   > Geräte (ein Gerät × Teiltyp 76-mal). Die Headline zählt jetzt **distinct Geräte
   > mit belegtem Frühausfall (hoch/mittel) ≈ 192**; die zeitbasierten ~527 Geräte
   > stehen separat als `ersatzteil_fruehausfaelle_zeitbasiert`. (< 7 Tage =
   > Doppelbuchung im selben Einsatz, weiterhin ausgefiltert.)
2. **Standzeit-Modell** (`vw_part_lifetime_stats`): Median-Standzeit je
   (Modell × Teiltyp) aus Intervallen ≥ 30 Tagen, ab 5 Stichproben → dient der
   **Vorhersage** (wann ist das Teil fällig → PM) und zeigt **störanfällige Teile**
   (auffällig kurze Standzeit, z. B. ein Modell, dessen Walzen im Median nach
   ~50 Tagen getauscht werden).

**Standzeit in Seiten (tagesgenau):** Zusätzlich zu Tagen wird die Standzeit in
**Seiten** berechnet. Ein Teil wird an einem konkreten **Tag** ein- bzw. ausgebaut,
darum lesen wir den Zählerstand der **nächstgelegenen Messung an diesem Tag** (nicht
einen Monatswert) — aus einer tagesgenauen Zähler-Zeitleiste je Gerät
(`device_counter_daily`, ~4,9 Mio. Geräte-Tage aus FleetMgmt-SNMP; Lookup via
`insights.page_at(gerät, datum)`). Seitenstand beim nächsten Tausch − beim Einbau =
gelaufene Seiten. Beispiele (Median): KM C754e Trommel ~200.000 Seiten, C458
~117.000, C650i ~95.000, C450i ~80.000.

**Hersteller-Soll für Ersatzteile (OEM-Nominal):** Die vom Hersteller angegebenen
Soll-Laufzeiten je Teil (Trommel, Fixiereinheit, Transferband, Walzen …) liegen in
der KRAI-Datenbank (`krai_pm.part_lifetimes`, aus einer Konica-Minolta-Excel,
`source=km_excel_v1.18`) und werden nach `insights.part_lifetime_oem` gespiegelt
(126 Werte, aktuell **nur Konica Minolta**: z. B. Trommel 180–300k, Fixiereinheit
540–840k, Transferband 360k–1,2M Seiten). Damit bewerten wir **pro Einzel-Tausch**: ein Teil, das **< 70 % seines OEM-Soll**
(Seiten) erreicht hat, ist ein Frühausfall (`vw_part_early_failures`, Spalte
`basis = OEM-Soll (Seiten)`, Konfidenz `hoch`). **Wo kein OEM-Soll existiert**, greift
seit Migration 045 **nicht mehr** die reine Zeitheuristik, sondern ein
**Vergleichs-Median in Seiten** (Modell → Hersteller → Teiltyp, Konfidenz `mittel`):
ein Teil, das unter 70 % der Laufleistung gleicher Teile liegt, ist ein Frühausfall —
ein Vielnutzer-Verschleiß mit hoher Seitenzahl wird so **nicht** mehr fälschlich
markiert. Nur Teile **ganz ohne Seitenbeleg** fallen auf die Zeitheuristik zurück
(Konfidenz `niedrig`, nicht in der Headline). Aktuell: 147 Geräte OEM-belegt
(Konica Minolta, `hoch`) + 46 Geräte über den Vergleichs-Median (`mittel`) =
**~192 belegte Geräte**; ~527 weitere nur zeitbasiert (`niedrig`). Beispiel: eine
Trommel, die nur 809 von 230.000 Soll-Seiten lief (Diagnose „Streifen auf Ausdruck").
Die Soll-Zuordnung läuft über die Teil-Kategorie (Teilenummer-genau wäre noch
genauer). HP/Lexmark bräuchten ihre eigene OEM-Soll-Liste (Excel) analog.

**Grenzen / To-do:**
- **Abdeckung ~26 % der Ersatzteil-Geräte:** von ~4.700 Geräten mit Teile-Einbauten
  sind ~2.450 per Seriennummer mit FleetMgmt verknüpft, und nur ~1.250 haben
  überhaupt eine SNMP-Seitenzähler-Historie (der Rest sind Radix-only- oder stille
  Geräte ohne Zählerdaten). Wo Zählerdaten fehlen, bleibt die Seitenzahl leer — die
  Tage-Standzeit steht aber immer. (Keine Ungenauigkeit, nur fehlende Quelle.)
- Teiltyp per Stichwort erkannt; „sonstige" ist noch ein großer Topf.
- Paarung über gleiche `article_code` — ein Nachfolger-Teil mit neuer Artikelnummer
  wird (noch) nicht gepaart.
- **Ticket-Langtext (Ausführungsbeschreibung):** enthält **Personennamen** (z. B.
  „Herr X nicht erreicht") und ist damit **PII** — wird NICHT roh gespeichert. Nur
  strukturierte, nicht-personenbezogene Felder (Datum, Status, Teil) sind nutzbar.

### Zwei getrennte Garantie-Ströme (Radix GAR)

Radix führt keinen eigenen Garantie-Objekttyp, aber Vorgänge mit
`invoicing_type = GAR` sind die **tatsächlich abgewickelte** Garantie-Arbeit — fast
ausschließlich **Field-Teile** (Fixierer, Trommel, Boards), in Radix mit € 0
(unter Garantie, nicht berechnet). Die Überschneidung mit unseren
**Toner**-Frühausfällen ist minimal (~2 von ~680 Geräten) → unsere Toner-Garantie
ist ein **separater, bislang weitgehend ungenutzter** Rückhol-Strom. GAR liefert
**keine** Hersteller-Frist und keinen €-Wert (€ 0) — der „noch einreichbar"-Schnitt
bleibt eine Geschäftsregel.

## 7. Quellen & Sichten

- Basis: `ACCMARKERREFILL` (FleetMgmt) → `vbm_lifecycle_events` → `vw_vbm_lifecycle`
  (Klassifikation, Fehlmeldungs-Flag) → `vw_warranty_assessment` (4-Quadranten).
- Aggregat: `vw_lagebericht` (Headline-Zahlen), `vw_warranty_by_manufacturer`
  (je Hersteller, mit erstattbarem Wert).
- Soll-Laufleistung: `ACCMARKERREFILL.CoveragePagesTarget` (OEM-Angabe).

## 8. Füllstand-Korrektur — Claim nur bei (nahezu) leerer Kartusche (Migration 053)

**Befund (2026-05-26, user-getrieben):** Die Claim-Logik flaggte jede Kartusche
mit < 70 % der (deckungsbereinigten) OEM-Reichweite als „claim" — **ohne zu prüfen,
ob die Kartusche beim Tausch überhaupt leer war**. Eine halbvoll herausgenommene
Kartusche druckt ebenfalls wenig Seiten und wurde fälschlich als Frühausfall gezählt.

Gemessen 2025: von 176 serial-belegten Claims waren nur **48 (27 %)** wirklich
(nahezu) leer; **115 (65 %)** wurden mit > 30 % Restfüllung getauscht (Ø 49 % voll).
Beispiel „Weiss_Automotive": 95 „Claims", aber der April-Spike (53) war ein
**Massen-Tausch halbvoller Kartuschen** (Ø 44 % Rest) — kein Defekt.

**Diskriminator:** `vw_vbm_lifecycle.level_last` = Füllstand der **ausgehenden**
Kartusche (0–100 %, FleetMgmt-SNMP). Echter Frühausfall = leer **und** < 70 %
geliefert (Short-Fill/Defekt). Hoher Füllstand = noch Toner drin → früh getauscht.

**Fix (`vw_warranty_assessment`):**
- `claim`/`negotiation` nur noch, wenn `level_last <= 20` **oder** unbekannt
  (NULL → konservativ behalten, um echte Claims bei fehlendem Füllstand nicht zu verlieren).
- **Neue Klasse `vorzeitiger_tausch`**: Kartusche mit `level_last > 20` rausgenommen.
  Kein Defekt, sondern **weggeworfener Toner**.

**Effekt:** Claims 2025 **221 → 108** (Ø Füllstand 3 %, Ø 34 % OEM = echte Short-Fills);
all-time **~3.174 → 488**. Die alte Headline war durch vorzeitige Tausche ~6× überhöht.

### Toner-Verschwendung als eigene Geld-Quelle (`vw_toner_waste`)
Die `vorzeitiger_tausch`-Fälle sind kein Müll, sondern eine **Recovery-/Beratungs-
Quelle**: der Kunde wirft nutzbaren Toner weg. `vw_toner_waste` aggregiert je Kunde:
Anzahl Tausche, Ø Restfüllung, geschätzter weggeworfener Wert (Restfüllung ×
Tonerpreis je Hersteller, Fallback Gesamt-Median aus `vw_toner_price_ref`).

2025: **279 vorzeitige Tausche ≈ 5.468 € weggeworfener Toner**. Top: Weiss_Automotive
(905 €, 83 Tausche, Ø 61 % Restfüllung), Stadt Konstanz (569 €), Hirschbrauerei (493 €).
→ Aktionsliste für Vertrag-/Beratungsgespräche statt Phantom-Garantieanträge.

> HINWEIS: `level_last` ist FleetMgmt-SNMP, auf 0–100 % begrenzt; außerhalb/NULL =
> unbekannt (dann altes Verhalten). Schwelle 20 % gewählt, weil Geräte „Toner
> ersetzen" typ. erst < ~10 % melden — > 20 % Restfüllung ist klar proaktiv.

## 9. Resttonerbehälter-Vorhersage über den Seitenzähler (Migration 055)

**Problem (user, 2026-05-26):** Kopierer messen den Resttonerbehälter (Waste-Box)
schlecht — **52 % aller Waste-Box-„Events" im FleetMgmt-VBM sind Rauschen**
(< 5.000 Seiten = kein echter Tausch), bei Lexmark XC/CX, HP E87xx und
Kyocera-Color **80–100 %**. Folge: der volle Behälter fällt erst auf, wenn er
voll ist → Lieferung zu spät.

**Lösung (`vw_waste_box_forecast`):** über den **Seitenzähler** (zuverlässig)
statt den Füllstand-Sensor prognostizieren. Pro Live-Gerät mit Waste-Box:
Seiten seit letztem ECHTEN Wechsel (pages_since_previous ≥ 5.000) vs. einer
Box-Reichweite Y je Modell:
1. **Modell-realisiert** — Median echter Wechsel je Modell, ≥ 5 Stichproben
   (verlässlich v. a. KM bizhub: C450i ~49k, C458 ~77k, C258/C308 ~43–45k S.).
2. **OEM-Soll Waste** je Hersteller (aktuell nur Lexmark ~35.500 S.).
3. **Flotten-Median** (Notnagel).

`mess_qualitaet`:
- **verlässlich** — innerhalb der aktuellen Box (Seiten seit Wechsel ≤ 1,2·Y) →
  echte Punkt-Prognose (`pct_voll`, `tage_bis_voll`).
- **unsicher (Wechsel nicht erfasst)** — Seiten seit letztem erfassten Wechsel
  ≫ Y (zwischenzeitliche Tausche als Rauschen verloren) → kein Punkt-Forecast.
- **unsicher (Sensor-Rauschen)** — kein einziger echter Wechsel erfasst → nur Y
  als Richtwert für eine **feste Liefer-Kadenz**.

`dringlichkeit` (nur für verlässliche): faellig ≥ 80 % · bald 60–80 % · ok.

**Ergebnis:** **61 fällig + 63 bald = verlässliche proaktive Liefer-Liste**
(überwiegend KM bizhub); 3.315 Geräte mit kaputtem Sensor sind ehrlich als
„unsicher" markiert (feste Kadenz nach Y). UI: Verbrauchsmaterial-Seite Tab
„🗑️ Resttonerbehälter"; Agent-Route `resttoner_vorhersage`.

## 10. OEM-Soll-Backfill — Garantie + Standzeit von 14 % auf 85 % der Events (Migration 062)

**Problem (Audit 2026-05-27):** Die OEM-Soll-Reichweite je Tonerwechsel
(`vbm_lifecycle_events.oem_target_pages`) war nur bei **14 %** der Ereignisse gesetzt
(28.312 / 199.170) — sie stammte aus der alten, engen Radix-Artikel-Quelle. Dadurch
„sah" sowohl die Garantie-Bewertung als auch die Standzeit-/Yield-Auswertung nur 14 %
der Tonerwechsel. **20.840 Ereignisse mit echtem Seitenlauf** (HP 15.258 / KM 3.014 /
Lexmark 2.358 / Kyocera 202) blieben unbewertet — obwohl die OEM-Reichweiten seit dem
VBM-Crawler längst vorliegen (sie waren nur nie in die Garantie-Pipeline verdrahtet).

**Lösung:** Eine materialisierte Tabelle `model_toner_oem` (Modell × Farbe → min /
**median** / max OEM-Toner-Seiten), einmalig aus der schweren Per-Gerät-Matching-View
`vw_device_supplies` aggregiert (NICHT pro Event joinen — Performance-Lektion aus
Migration 056; die View braucht ~25 s). `vw_vbm_lifecycle` fällt per COALESCE auf
diesen Modell-Soll zurück, wo der gespeicherte Radix-Wert fehlt (Radix behält Vorrang
→ die bisherigen Bewertungen ändern sich nicht). Wirkung propagiert automatisch in
Garantie **und** Yield (beide lesen `oem_target_pages` aus `vw_vbm_lifecycle`).

**Formel-Entscheidung — warum Median + Konfidenz:** Ein Modell hat oft 5–10 Toner-SKUs
(Starter / Standard / High / XL) mit **Ø 7,95× Spreizung** (z. B. Lexmark CX962se:
15.000 / 47.700 / **225.000** Seiten). Ein einzelner Wert wäre unzuverlässig: MIN
(Starter) würde echte Garantiefälle übersehen, MAX (XL) würde über-claimen. Wir nehmen
den **Median** als Soll (robust; für die Yield-Statistik über viele Geräte mittelt sich
das Rauschen weg) und führen die Spreizung als **`oem_target_spread`** mit. Daraus
leitet `vw_warranty_assessment` eine **`oem_konfidenz`** ab:
- **hoch** — Soll aus Radix belegt ODER Modell-Median mit enger Spreizung (≤ 2×, quasi Einzel-SKU)
- **mittel** — Modell-Median, Spreizung ≤ 4×
- **niedrig** — Modell-Median, Spreizung > 4× (unsichere Referenz → zeigen, nicht headlinen)

**Wirkung:**
- Bewertbare Tonerwechsel: **~19.600 → 34.998** (+15.400).
- Garantie-Claims: **488 → 574 belastbar** (hoch+mittel; +84 neue mit Spread ~1,1× und
  Ø 24,7 % der Soll-Reichweite = echte Frühausfälle) + **24 niedrig** (separat, manuell prüfen).
- Yield-/Standzeit-Bild: **von „53" auf 1.603 Modell/Farbe-Kombinationen** — endlich
  flotten-weit belastbar statt Stichprobe.
- Die Headline (`vw_lagebericht`) zählt nur hoch+mittel; `garantie_claims_niedrig` ist
  separat ausgewiesen. So bleibt die Glaubwürdigkeit gewahrt (kein Over-Claim wie früher).

**Scope & Grenze:** HP / Lexmark / Kyocera (über `vw_device_supplies` = ~85 % der
Lücke). **Konica Minolta (3.014 Events) fehlt noch**: KM hat keine per-Modell-
Kompatibilität (Excel-Pfad mit `model_family`-Codename wie „ZEUS") — der KM-Toner-Soll
braucht eine eigene bizhub→KM-Modellfamilie-Brücke (offener Folgeschritt). Leere
`colorant`-Events werden nur bei **Mono**-Modellen als Schwarz gewertet (bei Farb-
Modellen ist die leere Farbe der Gesamtzähler, NICHT die Schwarz-Patrone → nicht gemappt).

**Aktualisierung:** `refresh_model_toner_oem()` in `insights/etl/load.py`, läuft
automatisch bei `--vbm-crawler`, `--partlifetimes` und `--all` (nach jeder Änderung an
`part_lifetime_oem` / `devices_unified`). UI: Verbrauchsmaterial → Garantie-Bewertung
mit Konfidenz-Filter und Spalten „OEM-Konfidenz"/„Soll-Quelle".
