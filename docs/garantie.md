# Garantie & Geld zurückholen

Ziel: defekte Verbrauchsmaterialien (Toner, Trommeln) erkennen, die **vorzeitig
ausgefallen** sind, und den beim Hersteller reklamierbaren Wert beziffern — mit
belastbarem Nachweis.

## 1. Wann ist etwas ein Garantiefall?

Pro Material-Lebenszyklus (eingebaut → gewechselt) bewerten wir **zwei** Achsen:

- **Zeit:** Wie alt war das Teil beim Wechsel? (`age_days`)
- **Laufleistung:** Wie viele Seiten hat es geschafft, im Vergleich zur
  Hersteller-Soll-Laufleistung? (`pct_of_oem` = gelaufene Seiten / OEM-Soll)

Daraus die Einordnung (Sicht `vw_warranty_assessment`):

| Klasse | Bedingung | Bedeutung |
|---|---|---|
| **claim** (Garantiefall) | ≤ 365 Tage **und** < 70 % der Soll-Laufleistung | innerhalb Garantie früh ausgefallen → reklamieren |
| **negotiation** (Verhandlung) | > 365 Tage **und** < 70 % der Soll | außerhalb Zeit, aber klar unter Soll → Hebel ggü. Hersteller |
| **wear** (Verschleiß) | ≤ 365 Tage **und** ≥ Soll erreicht | normal verbraucht, kein Fall |
| **normal** | sonst | unauffällig |
| **artifact** | < 100 Seiten gelaufen | Sensor-Blip / Messartefakt (kein echter Zyklus) |
| **fehlmeldung** | Falschmeldung (siehe unten) | kein echter Wechsel |

**Warum 70 %?** Ein Teil, das deutlich unter seiner Soll-Laufleistung ausfällt, ist
glaubwürdig defekt. 70 % ist die Schwelle für „deutlich unter Soll"; sie filtert
normale Streuung heraus.

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
erstattbarer Anteil je Fall = 1 − (gelaufene Seiten / Soll-Laufleistung)
geschätzter Wert = Σ (erstattbarer Anteil) × mittlerer Tonerpreis
```

> **Schätzung, bewusst grob.** Der mittlere Tonerpreis (~105 €, Median) stammt aus
> den wenigen in Radix bekannten Materialpreisen (nur ~65 Preise). Der **€-Betrag
> ist eine Größenordnung**, kein exakter Wert. Die **Fallzahlen und die
> Laufleistungs-% sind dagegen hart belegt.** Eine belastbare €-Zahl braucht echte
> Stück-/Artikelpreise (aktuell nicht flächendeckend in den Daten).

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
- **€ nur für Toner** (Migration 042): das Rückhol-Potenzial nutzt den mittleren
  Tonerpreis und gilt daher nur für Toner-Fälle; CRU-Teile separat (andere Preise).
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

1. **Frühausfälle** (`vw_part_early_failures`): Teil innerhalb 7–365 Tagen erneut
   getauscht → Ausfall innerhalb der Garantie → Reklamation prüfen. (< 7 Tage =
   Buchung im selben Einsatz = Rauschen, ausgefiltert.) Aktuell ~4.000 Fälle.
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
`basis = OEM-Soll (Seiten)`). **Nur wo kein OEM-Soll existiert**, greift als Fallback
die 1-Jahres-Zeitheuristik (`basis = Zeit (1 Jahr)`). Aktuell: ~345 Fälle OEM-belegt
(Konica Minolta), ~3.700 über die Zeitheuristik — z. B. eine Trommel, die nur 809
von 230.000 Soll-Seiten lief (Diagnose „Streifen auf Ausdruck"). Die Soll-Zuordnung
läuft über die Teil-Kategorie (Teilenummer-genaue Zuordnung wäre noch genauer).
HP/Lexmark bräuchten ihre eigene Soll-Liste (Excel) analog.

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
