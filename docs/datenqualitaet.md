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
