# Agent-Routen (Assistent)

Der Chat-Assistent (Seite **Fragen**) wählt pro Frage **genau eine** deterministische
Route aus diesem Katalog (`insights/agent/routes.py`). Das LLM füllt nur die Parameter;
die SQL läuft fest gegen die `vw_*`-Views — die Zahlen sind also belegt, nicht erfunden,
und jede Antwort trägt eine Quelle (Citation). Passt keine Route, versucht der Dispatcher
einen abgesicherten Frei-Text-SQL-Fallback (nur SELECT auf `vw_*`); schlägt auch das fehl,
kommt eine Hinweis-Antwort mit Beispiel-Fragen.

> Diese Liste dokumentiert die Routen für Menschen — die maßgebliche Definition steht in
> `insights/agent/routes.py` (`REGISTRY`). Bei Änderungen bitte hier nachziehen.

## Geld & Garantie

| Route | Beantwortet | Wichtige Parameter |
|---|---|---|
| `lagebericht` | Gesamtüberblick: Rückhol-Potenzial €, Abrechnungsrisiko, Datenqualität, Service | — |
| `garantie_uebersicht` | Reklamierbare Garantiefälle, € und Verteilung nach Hersteller | — |
| `garantie_kandidaten` | Konkrete Garantie-/Verhandlungs-Fälle (serial-belegt) | `kunde`, `art` (claim/verhandlung) |
| `toner_verschwendung` | Halbvoll weggeworfene Kartuschen → weggeworfener € je Kunde | `kunde` |
| `toner_standzeit` | Reale Tonerlaufzeit vs. Hersteller-Soll je Modell | `farbe`, `modell` |
| `ersatzteil_fruehausfaelle` | Vorzeitig ausgefallene Teile (< 70 % Soll, seitenbelegt) | `kunde`, `teiltyp`, `nur_belegt` |
| `ersatzteil_standzeit` | Reale Median-Standzeit je Modell/Teiltyp | `modell`, `teiltyp` |

## Deckung & Vertrieb

| Route | Beantwortet | Wichtige Parameter |
|---|---|---|
| `deckung_kunden` | Kunden über Deckungs-Schwelle (Klickpreis-Nachberechnung) | `schwelle` |
| `deckung_geraete` | Einzelgeräte über Deckungs-Schwelle | `schwelle` |
| `entwickler_risiko` | Entwicklereinheit-Frühausfälle vs. Deckung | `nur_hohe_deckung` |
| `geraete_ohne_vertrag` | Aktive Geräte ohne Vertrag (Up-Sell) | `kunde` |
| `auslaufende_vertraege` | Verträge, die in 90 Tagen ohne Auto-Verlängerung auslaufen | — |
| `lizenz_verschwendung` | CSP-lizenzierte, aber inaktive Geräte (Delisting) | `risiko`, `kunde` |
| `fremdgeraete` | Wettbewerbs-Radar: Geräte ohne Radix-Link über den DCA | `nur_konkurrenz`, `kunde` |

## Service & Technik

| Route | Beantwortet | Wichtige Parameter |
|---|---|---|
| `fehlercode` | Bedeutung + Technik-Lösung zu einem Fehlercode | `code` (Pflicht) |
| `ticket_historie` | Service-/Ticket-Historie nach Gerät/Stichwort (Wissensbasis) | `geraet`, `suche` |
| `verbrauch_faellig` | Material/Teile, die bald fällig sind | `tage`, `kunde` |
| `resttoner_vorhersage` | Resttonerbehälter bald voll (über Seitenzähler) | `dringlichkeit`, `kunde` |
| `restlaufzeit_geraet` | Restlaufzeiten aller Materialien eines Geräts | `geraet` (Pflicht) |
| `problem_geraete` | Geräte mit auffällig vielen Alarmen | `kunde`, `nur_spam` |
| `problem_modelle` | Störanfälligste Modelle nach Alarm/Gerät | — |
| `haeufige_alarme` | Häufigste Alarm-Codes der Flotte | — |
| `offene_alarme` | Offene (nicht quittierte) Alarme, älteste zuerst | `kunde`, `min_tage` |

## Abrechnung & Datenqualität

| Route | Beantwortet | Wichtige Parameter |
|---|---|---|
| `abrechnungs_risiko` | Geräte unter Vertrag ohne aktuelle Meldung | `kunde` |
| `kosten_kunde` | Material-/Arbeitskosten je Kunde | `kunde` (Pflicht) |
| `kunden_abgleich` | Geräte mit abweichender Kundenzuordnung FleetMgmt↔Radix | `stufe`, `suche` |
| `material_einbau_pruefen` | Wo ein gebuchter Toner laut FleetMgmt eingebaut wurde | `status`, `suche` |
| `teilewechsel_validieren` | FleetMgmt-Teilewechsel gegen Radix (echt vs. Fake) | `suche` |
| `lieferadressen` | Radix-Lieferadressen eines Kunden | `kunde` |
| `print_server_kunden` | Kunden mit zentralem Print-Server (Queue-Phantome) | `kunde` |

## Nachschlagen

| Route | Beantwortet | Wichtige Parameter |
|---|---|---|
| `geraet_suchen` | Gerät über Serial/Radix-ID/Kunde/Modell/IP finden | `suche` (Pflicht) |
| `flotte_zaehlen` | Geräte zählen, gruppiert nach Hersteller/Status/Modell/Kunde | `nach`, `filter` |

## Robustheit (Dispatcher)

- **Tool-Name-Validierung:** Nur Routen aus `BY_NAME` werden ausgeführt — auch ein als
  Text emittierter Tool-Call (`_recover_tool_call`) wird gegen `BY_NAME` geprüft.
- **Enum-Guard:** `_one_of(...)` zwingt Enum-Parameter (z. B. `farbe`, `nach`) auf einen
  bekannten Wert oder den Default — ein ungültiger Wert führt nicht mehr still zu einem
  leeren Ergebnis.
- **Klare Fehlertrennung:** „KI-Dienst nicht erreichbar" (LLM-/Verbindungsfehler) ist von
  „keine passende Auswertung" (mit Beispiel-Fragen) unterschieden.
