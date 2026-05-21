# krai-insights

Standalone profitability & warranty analytics. Fuses three sources —
**FleetMgmt** (MSSQL), **KRAI** `krai_pm` (PostgreSQL) and **Radix** RxPlusService
(REST) — into an own PostgreSQL "Insights" DB, surfaces warranty-claim gaps,
validates VBM (consumable) lifespan against OEM spec, and ships a local
Ollama-powered agent for management/sales questions.

Fully decoupled from the KRAI monorepo. Sources are **strictly read-only**.

> Architecture, data model and the full phase plan live in
> `c:\Users\haast\.cursor\plans\krai-insights_side_project_ed1095c3.plan.md`.

## Status

**Phase 1 / Repo-Bootstrap.** Foundation, config, the Radix auth/token layer and
runnable skeletons are in place. Next: ETL extractors → device matcher →
`insights.devices_unified` → Device-Inventory dashboard.

## Prerequisites

- Docker + Docker Compose (Compose v2)
- Python 3.12 (for running tooling/tests on the host; the app itself runs in Docker)
- Network access to the source systems (FleetMgmt MSSQL, KRAI PostgreSQL, Radix API)

## Quickstart

```bash
# 1. Configure
cp .env.example .env          # then fill in passwords + Radix credentials

# 2. Start the core stack (Insights PostgreSQL + Streamlit app)
docker compose up -d insights-postgres app

# 3. Apply DB migrations
docker compose run --rm app python scripts/migrate.py

# 4. Open the dashboard
#    http://localhost:8501

# Optional — local LLM for the agent (Phase 5)
docker compose --profile agent up -d ollama
```

The source DBs (FleetMgmt MSSQL, KRAI PostgreSQL) are **external** and not part of
this compose file. When the app runs in Docker and a source runs on the host, set
its host in `.env` to `host.docker.internal`.

## Inputs needed from Tobias

| Input | Where it goes | Status |
|---|---|---|
| Radix credentials (`RADIX_USERNAME`, `RADIX_PASSWORD_BASE64`, `RADIX_CLIENT_CODE`, `RADIX_LICENSE_ID`) | `.env` | gathering |
| Top-15 customers + aliases | `config/customer_mapping.yaml` (see `.example`) | gathering |
| Warranty standard | confirmed **365 days flat** → `WARRANTY_DEFAULT_DAYS`; overrides in `config/warranty_rules.yaml` | done |

Verify Radix credentials once available:

```bash
docker compose run --rm app python scripts/radix_login_check.py
```

This logs in via `/api/authenticateApps/login/apps` and prints the raw response
keys — use them to confirm the token/expiry field names in
`insights/etl/radix/auth.py` against the live Infominds API.

## Project layout

```
insights/
  core/        config (pydantic-settings), logging, SQLAlchemy engines
  etl/
    radix/     RadixAuthManager (auto-refresh) + client + Pydantic models
    *_extractor.py   FleetMgmt / KRAI-PM / Radix extractors (read-only)
  matching/    device_matcher — fuse sources via (serial, internal_id)
  scoring/     VBM sensor-spam filter, lifespan rating, warranty valuation
  api/         repository layer (kept decoupled from UI)
  ui/          Streamlit app + pages
db/migrations/ sequential SQL migrations (NNN_*.sql)
scripts/       migrate.py, radix_login_check.py
config/        customer_mapping / warranty_rules (.example -> copy & fill)
tests/
```

## Development (on the host)

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1          # PowerShell  (Linux/mac: source .venv/bin/activate)
pip install -r requirements-dev.txt

pytest                               # tests
ruff check .                         # lint
mypy insights                        # type-check
python scripts/migrate.py --status   # show applied/pending migrations
```

## Design guardrails (from the plan)

- **No mutations to sources** — GET-only for Radix, SELECT-only for MSSQL/KRAI-PG.
- **Loose coupling to KRAI** — KRAI device UUIDs are stored as plain strings, no FK.
- **No auto-submit** of warranty claims — always a manual trigger (audit trail).
- **Data lineage** — every insight row carries `source_system` + `source_event_id`.
- **Pre-aggregated snapshots** for dashboards (sub-second reads).
- **Plain SQL migrations** (not ORM auto-migrate) so the schema stays portable.
