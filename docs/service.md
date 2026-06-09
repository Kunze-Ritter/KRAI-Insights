# Service — Teile-Einsatz & „Shotgun-Reparatur"

Ziel: Muster finden, wo bei einem Einsatz **auf Verdacht zu viele Teile** (Bildtrommel,
Entwickler, Transferband, Fixierer …) auf einmal getauscht werden, statt gezielt — um
Techniker zu schulen und Material-Kosten zu senken. Quelle: Migration 066
(`vw_service_visits`, `vw_symptom_part_patterns`, `vw_symptom_teiltyp`,
`vw_technician_service_profile`). UI: Seite **Service → Teile-Einsatz & Schulung**.

## Was ist ein „Einsatz"?

Ein Einsatz = eine Radix-Aktivität (`radix_activity_id`). Alle Material- und Arbeitszeilen
einer Aktivität gehören zusammen. Über die `radix_activity_id` lassen sich

- die **getauschten Teile** zählen (Positionen und verschiedene **Teiltypen**),
- der **Techniker** zuordnen (`employee_id` der Arbeitszeile — 97,9 % der Material-Einsätze
  haben eine), und
- der **Ticket-Freitext** (Problem/Technik) als **Symptom** klassifizieren

an einem Einsatz zusammenführen.

## Symptom-Klassifikation

`insights.service_symptom(text)` ordnet den Ticket-Freitext (Problem + Technik) einem
Symptom zu: **Papierstau, Bildqualität, Scanner/Einzug, Geräusch, Toner/Verbrauch,
Fehler/Störung, Wartung/Installation, Sonstiges**. Heuristik über deutsche Service-Notizen
(Schlagwörter). Die konkreten Stör-Symptome haben Vorrang vor generischer Fehler-Sprache;
**Wartung/Installation** greift nur, wenn gar kein Stör-Symptom vorkam.

### Warum Wartung getrennt wird (wichtig)

Viele Tickets sind **geplante Wartung oder Installation** („Wartung durchführen", „SD-Teile
installieren", „Treiber installieren"). Dort ist ein **Teile-Kit korrekt** — kein Shotgun.
Diese Einsätze werden separat ausgewiesen und **nicht** als Shotgun-Verdacht gezählt
(sonst würde geplante Wartung fälschlich als Verschwendung erscheinen).

## Shotgun-Verdacht

`shotgun_verdacht = (3+ verschiedene Teiltypen) UND (Symptom ≠ Wartung/Installation)`.
Drei oder mehr **verschiedene** Teiltypen bei einer Störung deuten auf „tausch mal alles
und hoff, dass es klappt". Es ist ein **Verdacht**, kein Beweis — einzelne Fälle vor einem
Schulungsgespräch im Tab „Shotgun-Einsätze" mit dem Ticket-Text prüfen (manchmal ist der
Mehrfach-Tausch berechtigt).

## Drei Auswertungen

1. **Symptom → Teil-Muster** (`vw_symptom_part_patterns` + `vw_symptom_teiltyp`): bei welchem
   Symptom werden wie viele/welche Teile getauscht und wie hoch ist die Shotgun-Quote. Befund:
   **Bildqualität** hat die höchste Quote (häufigste Kombi: Trommel) — klassisch „bei Streifen
   Trommel + oft Entwickler/Transfer mittauschen".
2. **Shotgun-Einsätze** (`vw_service_visits`, gefiltert): die konkreten Verdachts-Einsätze mit
   Teil-Kombination und Ticket-Text.
3. **Techniker-Profil** (`vw_technician_service_profile`): Shotgun-Quote und Ø Teiltypen je
   Techniker (ab 10 Einsätzen) — die Schulungs-Liste.

## Techniker-Zuordnung

Der Techniker kommt **direkt aus Radix** — die Aktivität trägt zwei Personen:

- **`employee` (= der AUSFÜHRENDE Techniker)** — identisch mit der Arbeitszeit-Zeile
  (`/activity/time`). Das ist der, der vor Ort gearbeitet hat. → `activity_notes.techniker_*`.
- **`employeeResponsible` (= Verantwortlicher / Dispo)** — oft Office (disponiert/hält das
  Ticket, war nicht vor Ort). → `activity_notes.dispo_*`, nur als Kontext.

Beides sind **eigene Mitarbeiter**, deren Namen laut Policy behalten werden dürfen (nur
Kunden-Kontakte werden pseudonymisiert). Befüllt vom Ticket-Crawl (`--tickets`),
Team aus `team`.

> Historie: Migration 067 hatte die Felder vertauscht (Dispo als Techniker). Migration 069
> korrigiert das — Techniker = `employee`. (Beleg: bei Tickets mit „Oliver Kraska" als
> `employeeResponsible` ist der `employee`/Worktime stets ein anderer, echter Techniker.)

Hat ein Ticket **keinen** zugewiesenen Techniker (kommt vor), fällt die Sicht auf den
Arbeitszeit-Logger zurück. Damit auch dann ein Name erscheint, pflegt der Ticket-Crawl eine
globale Namensliste `radix_employees` (`employee_id → Name`) aus **beiden** Feldern jeder
Aktivität (Logger `employee` + Verantwortlicher `employeeResponsible`); `vw_service_visits`
löst den Techniker darüber auf (Migration 068). So bleibt praktisch kein Techniker namenlos.

**Override (optional):** Will man kurze Kürzel statt voller Namen, mappt man
`employeeIdResponsible → Kürzel` in `config/technicians.yaml` (`--technicians`); das hat
Vorrang vor dem Radix-Namen. Ohne Override zeigt das Dashboard den Radix-Klarnamen.
(`scripts/seed_technicians.py` aus der ersten Version riet Kürzel aus dem Call-Log — seit die
echten Namen aus Radix kommen nicht mehr nötig.)

## Grenzen / Ehrlichkeit

- **Material-€ auf Verdachts-Einsätzen** ist ein Hinweis auf mögliche Über-Tausche, **kein
  bewiesener Verlust** — nur ~16 % der Material-Zeilen tragen einen Preis (Radix-Limit).
- Die Symptom-Klassifikation ist eine Heuristik; „Sonstiges" ist der größte Topf (Notizen ohne
  klares Symptom). Verfeinerung der Schlagwörter ist jederzeit möglich.
- Kein direkter Link zwischen FleetMgmt-**Fehlercodes** und dem Einsatz (zeitlich versetzt);
  das Symptom kommt aus dem **Ticket-Text**, nicht aus dem Maschinen-Alarm.
