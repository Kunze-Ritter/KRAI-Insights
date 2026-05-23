# Kennzahlen-Glossar

Jede Dashboard-Kennzahl in einem Satz: Bedeutung, Quelle, Detail-Doku.

## Übersicht (Wert-Board)

| Kennzahl | Bedeutung | Quelle / Detail |
|---|---|---|
| **Geschätztes Rückhol-Potenzial** | erstattbarer Garantiewert = Σ ungenutzte Restlaufzeit × Tonerpreis **je Hersteller** (zentral ~53.000 €), mit ausgewiesenem Band ~15.000–175.000 € (grobe Schätzung, nur 65 Preise) | [Garantie §4](garantie.md#4-was-ist-der--wert-restwert-modell) |
| **Reklamierbare Garantiefälle** | Materialien ≤ 1 Jahr alt und < 70 % der Soll-Laufleistung; Fehlmeldungen herausgerechnet | [Garantie §1–2](garantie.md#1-wann-ist-etwas-ein-garantiefall) |
| **davon serial-belegt** | mit Hersteller-Seriennummer = stärkster Nachweis (KM/Kyocera melden keine) | [Garantie §3](garantie.md#3-serial-belegt-vs-ohne-seriennummer-nachweis-stärke) |
| **Verhandlungs-Kandidaten** | > 1 Jahr, aber unter Soll-Laufleistung → Hebel ggü. Hersteller | [Garantie §1](garantie.md#1-wann-ist-etwas-ein-garantiefall) |
| **Still & unter Vertrag** | Geräte unter Vertrag ohne aktuelle Zählermeldung → Abrechnung auf Schätzwerten | [Datenqualität §3](datenqualitaet.md#3-abrechnungs-risiko) |
| **Kundenzuordnung prüfen** | Gerät hat in FleetMgmt und Radix verschiedene Kunden → Fehlversand-Risiko | [Datenqualität §1](datenqualitaet.md#1-kunden-abgleich-fleetmgmt--radix) |
| **Verbrauch in 14 Tagen fällig** | Toner/Teile, die bald leer sind → Tour-/Bestellplanung | — |
| **Auffällige Geräte** | sehr viele Alarme (defekte Sensoren / wiederkehrende Störungen) | — |

## Ersatzteile & Standzeit

| Kennzahl | Bedeutung | Detail |
|---|---|---|
| **Ersatzteil-Frühausfälle** | Teil lief unter 70 % einer **Seiten-Referenz** (Hersteller-Soll = Konfidenz `hoch`, sonst Vergleichs-Median = `mittel`); Headline zählt belegte **Geräte** (~192). Rein zeitbasierte (ohne Seitenbeleg) separat als `niedrig` | [Garantie §6](garantie.md#6-ersatzteile-nicht-nur-toner) |
| **Standzeit je Modell/Teil** | reale Standzeit (Median, Tage + Seiten) je Modell × Teiltyp aus Wiedereinbau-Intervallen → Vorhersage/PM + störanfällige Teile | [Garantie §6](garantie.md#6-ersatzteile-nicht-nur-toner) |

## Service-Qualität

| Kennzahl | Bedeutung |
|---|---|
| **Auffällige Geräte / Sensor-Spam** | ≥ 1.000 Alarme/Jahr = Sensor-Spam, ≥ 365 = erhöht (Field-Service-Kandidat) |
| **Störanfällige Modelle** | Alarme je Gerät (ab 5 Geräten, letzte 365 Tage) |
| **Häufigste Alarme** | Top-Alarm-Codes der Flotte mit betroffenen Geräten |
| **Offene Alarme** | noch nicht quittierte Alarme, älteste zuerst |

## Datenqualität & Abgleich

| Kennzahl | Bedeutung | Detail |
|---|---|---|
| **Abrechnungs-Risiko** | stille Geräte unter Vertrag | [Datenqualität §3](datenqualitaet.md#3-abrechnungs-risiko) |
| **Flotten-Abgleich** | Status + Vertrag + Vorhandensein in Radix je Gerät | — |
| **Teilewechsel-Validierung** | FleetMgmt-Wechsel mit Fake-Verdacht (kein Radix-Material) | — |
| **Material-Einbau** | wo ein gebuchter Toner wirklich eingebaut wurde | [Datenqualität §2](datenqualitaet.md#2-material-einbau-prüfung) |
| **Kunden-Abgleich (IP-Beleg)** | welches System bei abweichendem Kunden stimmt | [Datenqualität §1](datenqualitaet.md#welches-system-stimmt-der-ip-beweis) |

## Geräte-Status

`live` = Datentransfer ≤ 60 Tage · `silent` = > 60 Tage · `never_reported` = nie ·
`deactivated`/`deleted`. KPIs zählen i. d. R. nur `live`; PM nutzt auch
inaktive Historie. Siehe [Datenqualität §4](datenqualitaet.md#4-wiederkehrende-datenfallen).
