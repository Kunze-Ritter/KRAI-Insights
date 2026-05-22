# Datenquellen & Datenschutz

## Die drei Quellen (alle read-only)

| Quelle | System | Liefert |
|---|---|---|
| **FleetMgmt** | docuform, MSSQL | Geräte-Stammdaten, Zähler/SNMP-Historie (11 J.), Verbrauchs-/Teile-Wechsel (`ACCMARKERREFILL`), Alarme (`ACCEVENTHISTORY`), Netzwerk (IP/MAC/Hostname) |
| **Radix** | Infominds, REST-API | Service-Tickets, echte €-Kosten (Material/Arbeit), Verträge (Laufzeit), Kunden + Lieferadressen, die Radix-Geräte-ID (Such-Nr. der Mitarbeiter) |
| **KRAI** | PostgreSQL | Fehlercode-Wissen (Bedeutung + Technik-Lösung), Hersteller-/Produkt-Stamm |

Verknüpfung: Geräte über die **Seriennummer** (FleetMgmt `SerialNo` = Radix
`numberManufactor`). Geschrieben wird **nur** in die eigene Auswertungs-DB
(Schema `insights`); jede Zeile trägt Herkunft + Ladezeitpunkt und ist aus den
Quellen neu aufbaubar.

## Aktualität

Ein **nächtlicher Scheduler** lädt die Daten aus den Quellen: täglich die
Stammdaten/Zähler/Alarme/Kunden, wöchentlich die schwereren Radix-Crawls
(Verträge, Lieferadressen, Kosten). Das Dashboard zeigt also den Stand der letzten
Nacht; Einzelgeräte-Werte lassen sich bei Bedarf live nachladen.

## Datenschutz (DSGVO) — was wir NICHT laden

- **Ausgeschlossen:** E-Mail-Adressen, Personennamen/Ansprechpartner, Telefon/Fax,
  Anrede, Passwörter/PIN/SmartCard, Login-Daten, **Client-/Personen-IP**.
  Konkret werden diese Felder bei Radix-Kunden und -Lieferadressen (enthalten im
  Rohpayload) durch die Lade-Modelle **verworfen** und erreichen die DB nie.
- **Erlaubt:** Firmenname + Kundennummer, Standort (Straße/PLZ/Ort).
- **Mitarbeiter/Techniker:** in Kennzahlen/Kosten nur pseudonyme `employee_id`. **Ausnahme (Entscheidung):** in den **Ticket-Diagnosetexten** (Service-Historie) bleiben die Namen/Kürzel der **eigenen Techniker** erhalten — als Wissensbasis („wer hat das schon mal gelöst"). **Kunden-Ansprechpartner** und E-Mails in diesen Texten werden beim Laden pseudonymisiert (→ `[Kontakt]` / `[email]`, best-effort über deutschen Servicetext; ein bloßer Nachname ohne Anrede kann durchrutschen). Der fachliche Inhalt bleibt vollständig.
- **Drucker-IP/MAC/Hostname:** bewusst **behalten** — das ist Geräte-Infrastruktur
  (für den Service nötig, z. B. Neuinstallation wenn die Kunden-IT nicht erreichbar
  ist), kein Personenbezug. Eine Personen-IP (`ClientIPAddress`) bleibt ausgeschlossen.

## Bekannte Datenlücken (nachweislich nicht verfügbar)

- **Klickpreise (Erlösseite):** weder in FleetMgmt (`ACCCONTRACTS.PageCharge*` zu
  100 % leer) noch in Radix. → Profitabilität braucht eine vom Nutzer gelieferte
  Klickpreis-Tabelle. **Daher ist die Profitabilitäts-Auswertung aktuell auf Hold.**
- **Stückgenaue Materialpreise:** nur ~28 % der Radix-Materialzeilen tragen einen
  Preis → der €-Wert bei Garantie ist eine Größenordnung (siehe [Garantie](garantie.md#4-was-ist-der--wert-restwert-modell)).
- **Geräte→Lieferadresse:** die Radix-Service-API liefert die konkrete
  Lieferadresse je Gerät nicht → Lieferadressen nur pro Kunde.
- **Patronen-Seriennummer bei Konica Minolta/Kyocera:** wird nicht gemeldet (leer) →
  deren Garantiefälle sind über Zähler belegt, nicht über Serial.
