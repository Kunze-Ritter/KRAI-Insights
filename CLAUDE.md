# CLAUDE.md — krai-insights

Operational guide for working in this repo. Keep this file updated when architecture, commands, or key facts change.

## What this is

**krai-insights** = a standalone profitability & warranty analytics system that fuses three **read-only** sources into its own **Insights PostgreSQL**, queryable via a Streamlit UI and a local Ollama chat agent. It surfaces money: warranty claims to recover, OEM-vs-real toner yield, billing risk, profitability, predictive maintenance, and a technician error-code assistant.

- **Sources (READ-ONLY):** FleetMgmt MSSQL (docuform), Radix RxPlusService REST API (Infominds), KRAI PostgreSQL (`krai_*`).
- **Own DB:** `insights` schema in `krai-insights-postgres` — a **derived, disposable cache / materialized-view layer**, never a new source of truth. Every row carries `source_systems` + `ingested_at` and is rebuildable from sources.

The authoritative design + phasing lives in the approved plan: `C:\Users\haast\.claude\plans\pr-fe-bitte-ob-die-memoized-hennessy.md`. Long-term project memory: `C:\Users\haast\.claude\projects\C--Github-KRAI-Insights\memory\`.

## CRITICAL guardrails

- **Never `docker compose down -v`** — it deletes the 62M-row FleetMgmt volume AND `insights_pgdata`. Use plain `down` to stop.
- **Sources are strictly read-only:** SELECT-only against MSSQL/KRAI-PG, GET-only against Radix. Never DDL/DML/POST to a source. We only write to `insights.*`.
- **No PII (DSGVO):** never extract or store email, **customer/third-party contact-person names**, phone, or credentials. Company name + location (city) are OK. **Exception (user decision):** OWN technicians' names/initials in ticket free-text ARE kept (useful knowledge base — "who solved this before"); customer contact names + emails in that free-text are pseudonymised on load via `insights.core.pii.pseudonymize_contacts` (→ `[Kontakt]`/`[email]`, best-effort). Employees elsewhere stay pseudonymous (`employee_id`). **The printer's own management IP + MAC ARE kept** (`devices_unified.printer_ip`/`mac_address` from `ACCDEVICES.IPAddress`/`MACAddress`, `0.0.0.0`→NULL) — device infrastructure a technician needs to reinstall a copier when the customer's IT is unreachable; a person's client IP (`ACCUSERS.ClientIPAddress`) stays excluded. Extractors use explicit column whitelists (never `SELECT *` into the cache); Radix Pydantic models drop PII on validation. A schema PII-scan is part of verification.
- **All timestamps are UTC** (`TIMESTAMPTZ`). FleetMgmt server runs on UTC; use `ACCSNMPHISTORY.TimeUTC`; Radix returns `Z`. (Ruff enforces pyupgrade → use `datetime.UTC`, not `timezone.utc`.)
- **Radix `/api/activity` hangs unfiltered** — always scope by `CustomerId` or `TicketId` and paginate (`Take`/`Skip`). Fleet-wide crawl is a scheduled job, not a live chat call.

## Source systems

| Source | Container / Endpoint | DB / scope | Notes |
|---|---|---|---|
| FleetMgmt MSSQL | `krai-fleetmgmt-mssql` (host:1433) | `DevFleetMgmt`, login `krai_readonly` | 119 tables, 62,000,143 rows |
| Insights PG (RW) | `krai-insights-postgres` (host:5433) | `krai_insights`, schema `insights` | the only DB we write |
| KRAI PG | `krai-postgres-prod` (shared net) | `krai`, schema `krai_pm` (+ `krai_core`, `krai_intelligence`) | enrichment only; `krai_pm` mostly empty |
| Radix API | `https://radix.kunze-ritter.de/IM.RxPlusService.Api` | OpenAPI v26.12.0, 94 GET routes | JWT auto-refresh (`RadixAuthManager`) |
| Ollama | Windows-native via `host.docker.internal:11434` | `qwen2.5:7b` (tool-calling) | local LLM for the agent (Phase 4) |

Credentials live in `.env` (gitignored). Inside Docker, the app reaches sources by container name / `host.docker.internal`.

## Key commands

Run app-side things inside the running container; lint/tests via the local `.venv` (dev deps aren't in the prod image).

```powershell
# Migrations (plain SQL, checksum-tracked, idempotent)
docker exec krai-insights-app python scripts/migrate.py            # apply pending
docker exec krai-insights-app python scripts/migrate.py --status   # applied vs pending

# ETL (flags: --radix --vbm --models --errorcodes --contracts --costs --snmp --events --customers --shipping --vbm-crawler --all)
docker exec krai-insights-app python -m insights.etl.load              # FleetMgmt -> devices_unified
docker exec krai-insights-app python -m insights.etl.load --vbm-crawler # KRAI-Crawler-VBM JSON -> part_lifetime_oem + part_compatibility
docker exec krai-insights-app python scripts/radix_login_check.py      # Radix auth + read smoke

# Nightly scheduler (opt-in service; daily 02:00 + weekly Sun 03:00 UTC, read-only crawls)
docker compose --profile scheduler up -d scheduler                 # run on schedule
docker exec krai-insights-app python -m insights.etl.scheduler --once daily   # run a pipeline now

# Lint + tests (local venv — ruff/pytest are dev-only)
& "C:\Github\KRAI-Insights\.venv\Scripts\python.exe" -m ruff check insights
& "C:\Github\KRAI-Insights\.venv\Scripts\python.exe" -m pytest -q

# Ad-hoc FleetMgmt query (read-only)
docker exec krai-fleetmgmt-mssql /opt/mssql-tools18/bin/sqlcmd -S localhost -U krai_readonly -P '<see .env>' -C -d DevFleetMgmt -h -1 -W -Q "SELECT 1"

# UI: http://localhost:8501  (Streamlit; live code mount auto-reloads)
```

## Data model & fusion spine

- **Device join key (hard, exact):** FleetMgmt `ACCDEVICES.SerialNo` == Radix `serialnumber.numberManufactor`. Serial is NOT unique in raw FleetMgmt (372 dups) → `devices_unified` keys on `fleetmgmt_device_id`; serial is a non-unique match key; dups → `match_review_queue`.
- **Identifiers kept (agent can search by any):** `manufacturer_serial`, `radix_device_number` (Radix `serialnumber.number`, the staff search id), `fleetmgmt_device_id` (`ACCDEVICES.Id`), `internal_id` (regex from `Location`).
- **Device → customer (FleetMgmt):** `ACCDEVICES.SubmitterId → ACCUSERS.Id` (`Name` = company, non-PII; `DeviceManagerId` = the MSP "KunzeRitter", not the customer). Vendor: `VendorId → ACCDEVICEVENDORS.Vendor`.
- **`device_status`** ∈ live | silent | never_reported | deactivated | deleted. "Active" = data transfer within **60 days** (`ACCDEVICES.LastDataTransferDate`). Reality: of 11,950, only ~6,400 are live (~5,100 silent) — the admin "active" flag (11,815) overstates the fleet ~2×. KPIs default to `live`; PM keeps inactive history.
- **Models:** canonical = KRAI `krai_core` (`products.model_number/series/article_code`[empty]); OEM code = Radix `article.model` (e.g. `AA7R021`); FleetMgmt has only display name. Serial-join gives ground-truth name↔code pairs → `model_catalog` + `model_aliases`.
- **Money gaps:** material/labor € only from Radix (`/activity/sparepartprice`,`/time`). **Click prices (revenue) are NOT in any accessible system** (`ACCCONTRACTS.PageCharge*` 100% empty, Radix none) → need a user-supplied `config/contract_pricing.yaml`. Warranty fields empty → derive from install + 365d + per-mfr overrides.

Migrations applied: `001` (schema+pgcrypto), `002` (devices_unified, model_catalog, model_aliases, match_review_queue), `003` (serial non-unique + `vw_device_lookup`), `004` (vbm_lifecycle_events + `vw_vbm_lifecycle` + `vw_toner_yield_vs_oem`), `005` (widen coverage cols), `006` (fix yield view), `007` (vw_premature_failures — serial-backed warranty candidates), `008` (vw_model_code_backfill), `009`/`010` (vw_warranty_assessment — time+usage 4-quadrant, credibility-filtered), `011` (error_code_ref), `012` (device_contracts + renewal/out-of-contract views), `013` (cost_events), `014` (cost views: vw_cost_by_invoicing, vw_cost_by_customer), `015` (vw_vbm_validation: FleetMgmt change × Radix material), `016` (snmp_predictions + vw_consumables_due — predictive maintenance), `017` (vw_billing_risk + vw_fleet_reconciliation), `018` (vw_vbm_validation customer-level tier — handles material redistributed across a customer's fleet). **`019`–`044`** (further refinements: material-install check, fleet/network/customer-normalization + IP evidence, shipping, hostname, lagebericht, false-report filter + residual value + empty-serial fix + age0-artifact + **coverage-adjusted warranty (043)**, spare-part lifecycle + page-accurate lifetimes + OEM part assessment, coverage analytics). **`045`** (vw_part_early_failures **usage-validated**: < 70 % of an OEM/peer-median page reference + confidence tiers hoch/mittel/niedrig — fixes the time-only heuristic that mislabelled heavy-use normal wear; headline now counts distinct devices). **`046`** (warranty € **per-manufacturer toner price + uncertainty band**; honest spare-part headline; `vw_toner_price_ref`). **`047`** (VBM-crawler bridge: extends `part_lifetime_oem` with 4 cols, partial unique index for `source LIKE 'vbm_crawler:%'`, new `part_compatibility` m:n table, `vw_printer_supplies` view — see `docs/vbm_crawler_integration.md`). **`048`** (Imaging Unit = eigener Teiltyp `'Imaging Unit'` — Drum+Dev kombiniert, ≠ reine Trommel; `part_type()` + `vw_spare_part_events` OEM-CASE + Extractor `imaging_unit→imaging_unit`; Crawler `detectSupplyType` "Belichtungseinheit"→imaging_unit). **`049`** (ADF/Scanner-Wartung = Teiltyp `'Scanner/ADF'` — Crawler `adf_kit`→Kat. `adf`, OEM-CASE + `part_type()` erkennt ADZ/Dokumentenzuführung, vor Walze/Roller; Crawler crawlt zusätzlich `/printers/accessory/` für Fuser/Transfer/Maintenance/ADF). **`050`** (KM-Excel `image_unit_color` → Teiltyp `'Imaging Unit'` statt `'Trommel/Drum'` — bizhub Color-IUs = Drum+Dev; 356 KM-Events bekommen OEM-Soll 155k, KM-Trommel-Median entkoppelt auf 260k; nur OEM-CASE in `vw_spare_part_events`).

## Code layout

- `insights/core/` — `config.py` (pydantic-settings, all source URLs), `db.py` (SQLAlchemy engines), `logging.py`.
- `insights/etl/` — `fleetmgmt_extractor.py`, `krai_pm_extractor.py`, `radix_extractor.py`, `load.py`; `radix/` (`auth.py` [JWT, works — don't touch], `client.py`, `models.py` [PII-dropping]).
- `insights/matching/`, `insights/scoring/`, `insights/agent/` (Phase 4), `insights/ui/` (Streamlit).
- `db/migrations/NNN_*.sql` (applied by `scripts/migrate.py`). `config/*.yaml`.

## Conventions

- Plain sequential SQL migrations (portable back into KRAI later), not ORM auto-migration. Migrations take **no bind params**; the runner doubles literal `%` so it's safe in comments/LIKE. A view that depends on a column blocks `ALTER ... TYPE` → drop + recreate the view in the same migration.
- Pydantic v2 (`model_config = ConfigDict(...)`), `from __future__ import annotations`, type hints.
- Ruff is configured (pyupgrade etc.) — keep `ruff check` clean.
- **Document in parallel (user rule).** Every meaningful finding/decision (the *why*) goes into `docs/` (German, user-facing) as it happens — esp. analytics logic, data quirks, and known gaps. Dashboard metrics link to the relevant doc via tooltips/captions (`insights/ui/links.py` → GitHub `docs/`). Keep `docs/` in sync when logic changes.
- Commit only when asked. **Small/low-risk changes may commit + push directly to `main`** (bug fixes, UI tweaks, a single view/route, docs). **Larger changes go on a feature branch + PR** (new migrations with data impact, multi-file refactors, schema/PII changes, anything risky or worth review). When unsure, ask. Co-author trailer per repo policy.

## Status (2026-05-23)

**Review-Fixes (2026-05-23, branch `fix/assessment-credibility-and-agent-recovery`).** A full audit of the assessments + agent found and fixed three issues. (a) **Spare-part early failures** were time-only (any re-replacement in 7–365 d), flagging heavy-use normal wear as warranty (the 135 page-bearing time-flags ran a median 27.9k pages) and repeat-counting (4077 rows over 720 devices) → migration 045 requires < 70 % of an OEM/peer-median **page** reference, with confidence tiers; headline = distinct usage-validated devices (~192, was ~4077). (b) **Warranty €** rested on one global toner median (65 prices, biased high) → migration 046 prices per manufacturer (central ~53k €, was ~74k) and exposes a p10–p90 **band** (~15k–175k €). (c) **Agent BUG-A**: qwen2.5:7b sometimes emits the tool-call as text (`brtc {…}`) → `dispatcher._recover_tool_call` parses + runs it instead of leaking raw JSON. (d) **BUG-B analysis pass**: `_analyze` now grounds the LLM in the route's already-correct summary text (not just a raw table) + a stricter prompt (don't reinterpret a count as days/units) → fixes the "607 Tage" hallucination. (e) **GAP-C**: new deterministic route `flotte_zaehlen` (count devices by hersteller/status/modell/kunde) answers "wie viele Geräte hat X". (f) **LLM provider switch**: `insights/agent/llm.py` — `LLM_PROVIDER=ollama|openrouter`; OpenRouter (OpenAI-compatible) gives stronger free models with **automatic Ollama fallback** on 429/error (`FallbackLLMClient`) + 429 retry. `.env`: `OPENROUTER_API_KEY`/`OPENROUTER_MODEL`. NOTE: free `llama-3.3-70b:free` is often 429-saturated; `z-ai/glm-4.5-air:free` / `openai/gpt-oss-20b:free` were responsive + gave clearly better German analysis (verified live). To switch the running app, edit `.env` then `docker compose up -d app` (recreate so env reloads). Below status predates this review.


R0 (Radix client rewrite) done. Phase 1 in progress:
- `devices_unified` populated: 11,950 FleetMgmt devices; `vw_device_lookup` live (search by serial / Radix-ID / customer / model).
- Streamlit Device-Inventory page (`insights/ui/pages/1_Device_Inventory.py`) wired to the view.
- **Radix device enrichment done** (`load.py enrich_devices_from_radix`): 8,864 of 11,261 serial-bearing devices matched (~79%) → `radix_device_number`, `manufacturer_model_code` (OEM code), `production_date`, `radix_customer_id`; search-by-Radix-ID works. Non-sensitive only.

**Phase 2 (VBM-Lifecycle) started:** `vbm_lifecycle_events` loaded (199,170 events from ACCMARKERREFILL; `load.py --vbm`). `vw_vbm_lifecycle` classifies real_new_cartridge (112,813) / no_serial (68,666) / reinsert_same (17,691) + `likely_false_report` (29,237) via window over device×colorant. `vw_toner_yield_vs_oem` reproduces documented OEM-vs-real yields (E40040 ~104 pct, X58045 high); **fleet avg ~127 pct of OEM** across 53 model/colorant combos. Cartridge serial captured for warranty evidence + false-report detection. Streamlit **VBM-Lifespan page** (OEM-yield, false reports, warranty candidates, per-device toner history) + `vw_premature_failures` (6,133 candidates, 6,086 serial-backed).

**Model catalog seeded** (`load.py --models`): 2,342 canonical models (1,607 with Radix OEM code), 11,331 devices linked to `model_id`; `vw_model_code_backfill` is the OEM-code→KRAI `article_code` list (e.g. E40040→3PZ35A, C450i→AA7R021).

`device_matcher.run_matching()` done: match_type serial=8,864 / unmatched=3,086; 372 duplicate-serial groups in `match_review_queue` (internal_id→Radix-number fallback skipped — only ~30 extra matches).

**Warranty assessment done** (`vw_warranty_assessment`): per-lifecycle time+usage 4-quadrant — claim=3,277 (in 1yr & <70 pct rated) / negotiation=360 (>1yr & <70 pct → OEM leverage) / wear / normal / artifact (<100 pages noise filtered). Serial-backed.

**error_code_ref done** (`load.py --errorcodes`): 2,937 codes materialised from `krai_intelligence` (1,025 with technician solution; Lexmark/HP/Kyocera/KM) — the technician-assistant reference.

**Phase 3 started** (contract/cost import approved by user). **Contracts done** (`load.py --contracts`): 11,244 contracts crawled per device (concurrent), 6,640 devices under contract; `device_contracts` + `vw_contract_renewal_radar` (38 expiring <90d) + `vw_out_of_contract_devices` (305 up-sell). UI is German (st.navigation: Übersicht/Geräte-Inventar/Verbrauchsmaterial).

**Cost crawl done** (`load.py --costs [--cost-limit N]`): activities per customer → spareparts (price) + work times → `cost_events` (material/labor, `invoicing_type` VER-Vertrag/AUF-Aufwand/GAR-Garantie, `to_billed`). ~28 pct of material lines carry a charged price; labor in minutes (€ rate is config input). Full crawl ≈ 86k events / ~16 min.

Cost views (vw_cost_by_invoicing/by_customer) + Kosten&Verträge UI page done; full cost crawl loaded 88,187 events. **Phase 4 chat agent built** (`insights/agent/`: routes.py = 7 deterministic route tools over vw_*, ollama_client.py, dispatcher.py tool-calling; `views/fragen.py` page). **Agent is LIVE** — Windows-native Ollama (`qwen2.5:7b`) reached via `host.docker.internal:11434` (Windows set `OLLAMA_HOST=0.0.0.0:11434`; `.env` updated; app container recreated to load it). Verified end-to-end: questions route correctly to tools ("Fehlercode 200.03", "Gerät 144052", "Verträge laufen aus", "Toner-Standzeit C450i"). `profitability_snapshots` still gated on click prices + labour rate (after holiday) — or the official Core API. **Radix contract/cost import is gated on a pending user governance decision** (see `todo.md`). In-app chat agent = Phase 4 (Ollama; `krai-ollama-prod` was stopped at last check). See the plan + memory for the full roadmap.
