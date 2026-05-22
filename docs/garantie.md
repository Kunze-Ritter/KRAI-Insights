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

**Grenzen / To-do:** Standzeit aktuell in **Tagen** (Zählerstand beim Einbau ließe
sich aus der Ticket-/Zähler-Historie ergänzen → Standzeit in Seiten). Teiltyp wird
per Stichwort aus der Artikelbeschreibung erkannt; „sonstige" ist noch ein großer
Topf (Klassifikation verfeinerbar). Paarung über gleiche `article_code` — ein
Nachfolger-Teil mit neuer Artikelnummer wird (noch) nicht gepaart.

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
