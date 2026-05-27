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
