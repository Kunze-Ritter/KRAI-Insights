# Datenqualität & Abgleich

FleetMgmt (Flotten-Verwaltung) und Radix (Service-System) werden gegeneinander
geprüft — für saubere Abrechnung, korrekte Geräte-Zuordnung und weniger
Toner-Fehlversand.

## 1. Kunden-Abgleich (FleetMgmt ↔ Radix)

Ein Gerät wird über die **Seriennummer** in beiden Systemen verknüpft. Dann
vergleichen wir den zugeordneten **Kunden**. Da Kunden uneinheitlich angelegt sind
(Unterstriche, Rechtsformen, Tippfehler), normalisieren wir die Namen vor dem
Vergleich (`insights.norm_company_name`: Kleinschreibung, Umlaute, Rechtsform wie
GmbH/AG/KG entfernt).

Einordnung (Sicht `vw_customer_device_mismatch`):

| Stufe | Bedeutung |
|---|---|
| **uebereinstimmung** | gleicher Kunde (nur andere Schreibweise) |
| **teilweise** | gemeinsamer Namensteil (≥ 4 Zeichen) → wahrscheinlich gleich |
| **abweichung** | kein Überlapp → prüfen (Besitzerwechsel oder falsche Zuordnung) |

**Häufigste Ursache einer echten Abweichung:** ein **gebraucht gekauftes Gerät** —
der neue Kunde steht in Radix, FleetMgmt hat noch den alten. → im Fleet/CSP
korrigieren, sonst landet Toner beim falschen Kunden.

### Welches System stimmt? Der IP-Beweis

Bei einer Abweichung ist die **aktuelle IP des Geräts der Schiedsrichter**: Ein
Gerät, das im IP-Subnetz (`/24`) eines Kunden meldet, steht physisch dort. Wir
prüfen, ob **andere Geräte** des FleetMgmt-Kunden bzw. des Radix-Kunden dasselbe
Subnetz nutzen (`subnetz_passt_zu`):

- **fleet** → IP bestätigt FleetMgmt (Radix korrigieren)
- **radix** → IP bestätigt Radix (Fleet/CSP korrigieren)
- **beide / unklar / kein_ip** → Subnetz nicht eindeutig (z. B. Standard-Netz
  192.168.1.x, das viele Kunden nutzen)

> **Wichtige Erkenntnis:** „Radix ist immer aktuell" stimmt **nicht** pauschal. Im
> geprüften Fall RS-Technik/Schafhäutle meldete das Live-Gerät aus dem Subnetz von
> Schafhäutle → hier war FleetMgmt richtig und Radix veraltet. Die Live-IP
> entscheidet, mal so, mal so.

## 2. Material-Einbau-Prüfung

Ein in Radix gebuchter Toner kann laut FleetMgmt auf einem **anderen** Gerät
desselben Kunden eingebaut worden sein (`vw_material_install_check`): `korrekt` /
`woanders_eingebaut` (Falschbuchung / Lager-Umverteilung) / `kein_einbau_gefunden`.
Begrenzung: Der Geräte→Lieferadresse-Link ist in der Radix-Service-API nicht
abrufbar, daher lösen sich Lieferadressen nur **pro Kunde** auf, nicht pro Gerät.

## 3. Abrechnungs-Risiko

Geräte **unter Vertrag**, die keine Zähler mehr melden (`silent`/`never_reported`),
werden auf **Schätzwerten** statt echten Zählern abgerechnet → `vw_billing_risk`.
Diese sollten vor Ort/mit der Kunden-IT geprüft werden (Collector offline,
Server-Tausch, Netzwerk).

## 4. Wiederkehrende Datenfallen

- **Leerstring `''` ≠ NULL.** FleetMgmt schreibt häufig leere Strings statt NULL —
  bei Patronen-Seriennummern (Konica Minolta/Kyocera) und bei `IPAddress = '0.0.0.0'`.
  Beide werden beim Laden zu NULL normalisiert, sonst entstehen Fehlklassifikationen
  (siehe der Garantie-Fehlmeldungs-Bug in [Garantie](garantie.md#2-fehlmeldungen-herausfiltern-wichtig)).
- **Geräte-Status:** „aktiv" = Datentransfer in den letzten **60 Tagen** (nicht 30 —
  deckt ~9 Wochen Sommerferien ab). Der Admin-Flag „aktiv" überzeichnet die Flotte
  ~2× (echte Live-Geräte ~6.400 von ~11.950).

## Lizenz-Verschwendung (vw_lizenz_verschwendung, Migration 057)

**Problem (user):** CSP nimmt Geräte automatisch unter Lizenz — auch solche, die der
Kunde nur noch herumstehen hat (abgebaut, ersetzt, offline). Das kostet pro Gerät
Lizenzgebühr ohne Gegenwert.

`vw_lizenz_verschwendung` listet **Delisting-Kandidaten**: Geräte, die noch
CSP-lizenziert sind (`device_status NOT IN ('deleted','deactivated')` = die ~11.815
„aktiven", deckt sich mit dem Admin-Flag), aber **nicht mehr `live`** sind — sie kosten
Lizenz, liefern aber nichts.

Stufen (`lizenz_risiko`), nach Delisting-Sicherheit:
- **hoch** — nie gemeldet, ODER > 365 Tage still **und** nicht in Radix, ODER ohne
  Modell/Hersteller (Phantom). Fast sicher weg.
- **mittel** — > 180 Tage keine Daten.
- **niedrig** — 60–180 Tage still (kann temporär offline sein).

Je Zeile der `grund` (still seit X Tagen / nicht in Radix / ohne Modell / kein Vertrag)
für die manuelle Prüfung vor dem Delisting.

**Stand 2026-05-27:** 5.412 Kandidaten von 11.815 lizenzierten — davon **2.515 „hoch"**.
Einsparung = Anzahl × Lizenzgebühr je Gerät. UI: Datenqualität-Tab
„💸 Lizenz-Verschwendung"; Agent-Route `lizenz_verschwendung`.

> Abgrenzung: Ein Gerät, das **live** meldet, ist KEINE Lizenz-Verschwendung (es ist
> in Benutzung) — auch ohne Vertrag (das ist Up-Sell, siehe `vw_out_of_contract`).

## Spionage / Wettbewerbs-Radar (vw_fremdgeraete, Migration 059)

**Idee (user):** Wird der DCA/CSP-Agent nach Vertragsende auf dem Kundenserver nicht
deinstalliert, melden sich dort weiter ALLE Geräte automatisch in die Flotten-
Verwaltung — auch die NEUEN (Konkurrenz-)Geräte, die der Kunde aufstellt. Wir sehen
sie, obwohl wir sie nicht servicieren = Wettbewerbs-Intelligenz.

`vw_fremdgeraete`: **live** (meldet aktuell) UND **nicht in Radix** (kein KR-Service-
Link). Flags:
- `konkurrenzmarke` — Marke ist nicht KR-Kern (KM/Lexmark/HP/Kyocera) → Canon/Brother/
  Sharp/Epson/… = starker Konkurrenz-Verdacht.
- `neu_aufgetaucht` — deployed in den letzten 365 Tagen (frisch dazugestellt).
- `einordnung` — `verlorener_kunde_agent_aktiv` (keine KR-Geräte mehr beim Kunden →
  Win-Back oder Agent deinstallieren) vs. `fremdgeraet_bei_aktivem_kunden`.
- `unmanaged`-Geräte sind ausgeschlossen.

**Stand 2026-05-27:** 173 Fremdgeräte (live, nicht Radix), davon **23 Konkurrenzmarke,
22 neu** — z. B. Brother MFC @ Wobak Konstanz, Sharp BP-70C31 @ Weingut Schloss
Ortenberg, Canon TX-3200 @ Stadt Konstanz (mit Aufstell-Datum). UI: Datenqualität-Tab
„🕵️ Spionage / Fremdgeräte"; Agent-Route `fremdgeraete`.

## Print-Server-/Queue-Artefakte (vw_print_server_kunden, Migration 060/061)

**Befund (user-Frage „was sind die Geräte ohne Serial bei Bruderhaus?"):** Manche
Kunden werden NICHT geräteweise, sondern über einen **zentralen Windows-Print-Server**
überwacht. Der DCA liest dort die Druck-Warteschlangen mit; Queues ohne SNMP-Antwort
landen als „Geräte" mit dem **Queue-Namen im IP-Feld** (kein Serial, kein Modell, kein
Hersteller, kein MAC) = Spooler-Artefakte, keine physischen Kopierer.

Jeder Kunde hat ein eigenes Namensschema (der String selbst ist also kein
verlässlicher Erkenner):

| Kunde | Schema | Queue-Artefakte |
|---|---|---|
| Stadt Freiburg | `konicasq…` (Konica Secure Queue), `DN-…` | 104 |
| IMS Gear | `mfde…`, `konica…` | 218 |
| BruderhausDiakonie | `PS30…` (Print Server) | 82 |
| Allweiler / Landratsämter / Rolls-Royce | `PDERAD…`, `kop…`, `DEFDHPR…`, `MFP…` | je 1–4 |

**Robuster Erkenner (Migration 061, generierte Spalte `is_queue_artifact`):**
`printer_ip` ist gesetzt, aber **keine gültige IPv4** (= ein Hostname/Queue-Name)
**UND** keine Hersteller-Seriennummer (= keine echte Geräte-Identität). Geräte, die nur
zufällig einen Hostnamen im IP-Feld haben, aber ein Serial tragen (63 Stück), bleiben
echte Geräte und werden NICHT geflaggt.

**Wirkung:** flotten-weit **414 Queue-Artefakte** (96 live, 318 still). Sie werden aus
der **Live-Zahl** (`vw_lagebericht.geraete_live`, ~6.396→6.300) und der
**Lizenz-Verschwendung** herausgerechnet (die 318 stillen Phantome wurden vorher
fälschlich als „hoch"-Delisting-Kandidaten gezählt). `vw_fremdgeraete` filtert sie
schon seit Migration 060 über die fehlende Geräte-Identität.

`vw_print_server_kunden` listet je Kunde `queue_artefakte`, `echte_live_geraete`
(real überwachte Geräte), `namensschema` und ein `beispiel_queue`. **Wichtig:**
Diese Print-Server-Kunden sind KEINE Blindstelle — z. B. Bruderhaus hat neben den 82
Phantomen 577 echte, gut überwachte Live-Geräte (634 in Radix). Die Queues selbst
tragen keine Zähler/Toner-Daten und keine Service-Alarme (nur „Monitoring aktiviert/
entfernt") → für Service nichts zu holen. **Nutzen:** Cleanup (Agent bei Vertragsende
deinstallieren) + Erklärung, woher Phantom-Geräte stammen. UI: Datenqualität-Tab
„🖨️ Print-Server / Queues"; Agent-Route `print_server_kunden`.
