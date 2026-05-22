# KRAI Insights — Dokumentation

Diese Dokumentation erklärt **was** die Auswertungen zeigen, **woher** die Daten
kommen und **warum** wir bestimmte Entscheidungen getroffen haben. Sie ist die
Begründung hinter den Zahlen im Dashboard — jede Kennzahl soll nachvollziehbar und
belegbar sein.

## Inhalt

- **[Datenquellen & Datenschutz](datenquellen.md)** — die drei Quellen (FleetMgmt,
  Radix, KRAI), wie sie zusammengeführt werden, was wir bewusst NICHT laden (PII),
  und welche Daten nachweislich nicht verfügbar sind (z. B. Klickpreise).
- **[Garantie & Geld zurückholen](garantie.md)** — wie ein Garantiefall erkannt
  wird (Zeit + Laufleistung), wie Fehlmeldungen herausgefiltert werden, das
  Restwert-Modell für den €-Wert, und der wichtige Zeitfenster-Hinweis (was ist
  heute noch einreichbar).
- **[Datenqualität & Abgleich](datenqualitaet.md)** — Kunden-Abweichungen
  FleetMgmt↔Radix mit IP-Beweis, Material-Einbau-Prüfung, Abrechnungsrisiko, und
  wiederkehrende Datenfallen (Leerstring vs. NULL).
- **[Kennzahlen-Glossar](kennzahlen.md)** — jede Dashboard-Kennzahl in einem Satz:
  Bedeutung, Quelle, und wo es im Detail steht.

## Grundprinzipien

1. **Quellen sind read-only.** Wir lesen aus FleetMgmt (MSSQL), Radix (REST) und
   KRAI (PostgreSQL) und schreiben **nur** in unsere eigene Auswertungs-Datenbank.
   Diese ist ein abgeleiteter Cache und jederzeit aus den Quellen neu aufbaubar.
2. **Kein Personenbezug (DSGVO).** Keine E-Mail, Namen, Telefonnummern. Firma +
   Standort sind ok. Details in [Datenquellen & Datenschutz](datenquellen.md).
3. **Nachvollziehbar statt geraten.** Der Chat-Agent rechnet mit hinterlegten
   Formeln über geprüfte Sichten (Views) — keine erfundenen Zahlen. Schätzungen
   sind als solche gekennzeichnet.
4. **Stand der Daten:** Die Auswertungs-Datenbank wird nächtlich aus den Quellen
   aktualisiert (siehe [Datenquellen](datenquellen.md)).

> Diese Doku wird parallel zur Entwicklung gepflegt. Wenn sich eine Logik ändert,
> wird hier das Warum dokumentiert.
