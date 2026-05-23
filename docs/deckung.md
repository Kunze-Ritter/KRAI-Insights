# Deckung & Kalkulation

Ziel: sichtbar machen, **welche Kunden mit mehr als der kalkulierten Deckung
drucken** (Klickpreis-Nachberechnung) und **wo hohe Deckung Entwicklereinheiten
früher kaputtmacht** (Service-Hinweis). Grundlage ist dieselbe deckungskorrigierte
Datenbasis wie bei der [Garantie](garantie.md).

## Was ist „Deckung"?

**Deckung** = der Anteil einer Seite, der mit Toner bedeckt ist. Hersteller geben
die Soll-Laufleistung einer Patrone bei **5 % Deckung** an (ISO/IEC 19752 für S/W).
Je mehr Fläche pro Seite bedruckt wird, desto mehr Toner pro Seite — bei gleicher
Patrone also **weniger Seiten**.

Die Flotten-Software liefert die reale Deckung je Patronen-Lebenszyklus
(`CoveragePercentIs`). Wir bilden daraus die **seitengewichtete Durchschnitts-
deckung** je Gerät und Kunde:

```
Ø Deckung = Σ(gelaufene Seiten × reale Deckung) / Σ(gelaufene Seiten)
```

Seitengewichtet, damit eine kurzlebige Patrone mit Ausreißer-Wert das Ergebnis
nicht verzerrt. Nur plausible Werte gehen ein (Deckung 0,5–100 %, Patrone mit
> 0 gelaufenen Seiten); Geräte/Kunden brauchen eine Mindest-Seitenmenge
(Gerät ≥ 500, Kunde ≥ 1.000 Seiten), damit der Schnitt belastbar ist.

## 1. Klickpreis-Nachberechnung — Kunden über 6 %

Unser Unternehmen kalkuliert den **Klickpreis mit ~6 % Deckung** (großzügiger als
die ISO-5 %). Ein Kunde, der dauerhaft **über 6 %** druckt, verbraucht mehr Toner,
als im Klickpreis eingepreist ist — der Vertrag ist für uns dann unrentabel und ein
**Kandidat für Nachberechnung / Vertragsanpassung**.

Sicht `vw_coverage_by_customer` liefert je Kunde:

| Spalte | Bedeutung |
|---|---|
| `avg_deckung_pct` | seitengewichtete Ø-Deckung des Kunden |
| `ueber_klickpreis_6pct` | `true`, wenn Ø-Deckung > 6 % (über Klickpreis-Annahme) |
| `ueber_iso_5pct` | `true`, wenn Ø-Deckung > 5 % (über ISO-Soll) |
| `gedruckte_seiten`, `geraete` | Volumen-Basis (Mindest-Schwelle 1.000 Seiten) |

Im Dashboard (**Deckung & Kalkulation → Kunden über Klickpreis-Deckung**) lässt sich
die Schwelle frei einstellen; der Chat-Agent beantwortet „Welche Kunden drucken über
6 % Deckung?" über die Route `deckung_kunden` (Parameter `schwelle`, Standard 6).

> **Wichtig:** Die Deckung ist ein **historischer Schnitt** über alle erfassten
> Patronen des Kunden, kein Tageswert. Für eine Nachberechnung den konkreten
> Vertragszeitraum und das tatsächliche Volumen gegenprüfen.

## 2. Entwicklereinheit-Risiko bei hoher Deckung

**Tipp von HP:** Wird dauerhaft über ~5 % Deckung gedruckt, gerät in der
Entwicklereinheit das **Verhältnis von Toner zu Entwickler** aus der Balance. Die
Folge sind **vorzeitige Ausfälle der Entwicklereinheit** — ein echtes Service-Thema,
das man am Gerät erkennen und dem Kunden erklären kann.

Sicht `vw_developer_unit_risk` verbindet die **Entwicklereinheit-Frühausfälle**
(aus `vw_part_early_failures`, Teiltyp = `Entwickler`: innerhalb ~1 Jahr erneut
getauscht) mit der **Ø-Deckung des Geräts** (`vw_device_coverage`):

| Spalte | Bedeutung |
|---|---|
| `entwicklereinheit` | das ausgefallene Teil (Beschreibung, ggf. mit Farbe) |
| `standzeit_tage` / `standzeit_seiten` | wie lange/viel das Teil gehalten hat |
| `avg_deckung_pct` | Ø-Deckung des Geräts (leer, wenn keine Deckungsdaten) |
| `deckung_ueber_5pct` | `true`, wenn Geräte-Deckung > 5 % (HP-Risikoschwelle) |

**Hohe Deckung + kurze Standzeit = wahrscheinlich genau der HP-Effekt.** Im
Dashboard (**Deckung & Kalkulation → Entwickler-Risiko**) optional auf „nur über
5 %" filtern; der Agent nutzt die Route `entwickler_risiko`
(Parameter `nur_hohe_deckung`).

> **Bekannte Grenze:** Die Zuordnung läuft heute auf **Geräte-Ebene** (Ø-Deckung des
> ganzen Geräts), nicht je Farbe. Eine farbgenaue Zuordnung (z. B. „Cyan Developer
> Unit" gegen die Cyan-Deckung) ist eine spätere Verfeinerung — aktuell haben nur
> wenige Frühausfälle einen belegten hohen Deckungswert am Gerät, weil
> Entwicklereinheit-Wechsel und Toner-Deckungsmeldungen nicht immer am selben Gerät
> zusammenkommen.

## 3. Quellen & Sichten

- `vw_device_coverage` — Ø-Deckung je Gerät (seitengewichtet, ≥ 500 Seiten).
- `vw_coverage_by_customer` — Ø-Deckung je Kunde + 6 %/5 %-Flags (≥ 1.000 Seiten).
- `vw_developer_unit_risk` — Entwickler-Frühausfälle × Geräte-Deckung.
- Basis: `vw_vbm_lifecycle` (reale Deckung je Patrone), `devices_unified`,
  `vw_part_early_failures`. Migration `044_coverage_analytics.sql`.
- Deckungs-Logik im Detail (5-%-Soll, Deckungskorrektur): [Garantie §1](garantie.md#1-wann-ist-etwas-ein-garantiefall).
