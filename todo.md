# TODO — krai-insights

Master backlog. Kept lean by **category files** (so this doesn't get too full):

- [`todo_security.md`](todo_security.md) — Sicherheit / Zugriff / Deployment-Härtung
- (weitere bei Bedarf: `todo_governance.md`, `todo_data_quality.md`, …)

Der vollständige Roadmap-/Phasenplan liegt separat: `C:\Users\haast\.claude\plans\pr-fe-bitte-ob-die-memoized-hennessy.md`. Diese Datei sammelt nur **offene Entscheidungen + Merker**.

---

## Offene Entscheidungen (warten auf Input)

- [x] **Radix-Vertragsdaten importieren?** ✅ importiert (11.244 Verträge, Renewal-Radar, Out-of-Contract).
- [ ] **Profitabilität — auf HOLD bis nach dem Urlaub.** Erlösseite fehlt in allen Systemen. Nach Urlaub auszufüllen:
  - `config/contract_pricing.yaml` (← `*.example.yaml`): **Klickpreise** S/W + Farbe (je Vertragstyp; ihr habt unterschiedliche).
  - `config/business_rules.yaml` (← `*.example.yaml`): **Arbeits-Stundensatz/-sätze** — Radix liefert nur Minuten, keinen €-Betrag, und keine Rechnungs-/Satz-Route → nicht aus Radix ableitbar, muss von euch kommen.
  - Danach: `profitability_snapshots` (Erlös − Material − Arbeit + Garantie-Rückhol-Wert).

## Feature-Wünsche / Merker

- [ ] **In-App Chat-Agent** (OpenWebUI-artig) auf der bestehenden App — Fragen wie „ID 144052: Tonerstand/letzter Wechsel/Garantie", „Fehlercode XY", „welche Geräte melden nicht". Entspricht Phase 4 (Routen-Katalog + lokales Ollama). Erste Minimalversion könnte über `vw_device_lookup` schon jetzt laufen.
- [ ] **App-Bereitstellung für Mitarbeiter** klären (intern erreichbar machen) — siehe `todo_security.md`.

## Phase-1-Rest (in Arbeit)

- [x] Radix-Geräte-Anreicherung (`radix_device_number`, OEM-Modellcode, `production_date`) → „Suche per Radix-ID" ✅ (8.864/11.261 ~79% per Serial gematcht).
- [ ] `device_matcher` (Serial→Radix; Dubletten → `match_review_queue`).
- [ ] Modell-Katalog-Seed (`model_catalog`/`model_aliases` aus Serial-Join; OEM-Code → KRAI `article_code`-Backfill-Liste).
