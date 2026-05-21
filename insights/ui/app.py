"""
krai-insights — Streamlit entry point (Home / system status).

Run locally:
    streamlit run insights/ui/app.py
Or via Docker:
    docker compose up -d insights-postgres app   # -> http://localhost:8501

This Home page is a Phase-1 sanity check: it shows which sources are configured
and lets you ping the Insights DB. Analytics pages land under ui/pages/ as the
ETL + schema todos complete.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `streamlit run insights/ui/app.py` from the repo root without install.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st  # noqa: E402
from sqlalchemy import text  # noqa: E402

from insights import __version__  # noqa: E402
from insights.core.config import get_settings  # noqa: E402
from insights.core.db import insights_engine  # noqa: E402

st.set_page_config(page_title="krai-insights", page_icon="📊", layout="wide")
settings = get_settings()

st.title("📊 krai-insights")
st.caption(f"Profitability & warranty analytics · v{__version__} · env={settings.app_env}")

st.subheader("System status")
col_db, col_sources = st.columns(2)

with col_db:
    st.markdown("**Insights DB** (read/write)")
    if st.button("Ping Insights DB"):
        try:
            with insights_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            target = f"{settings.insights_db_host}:{settings.insights_db_port}/{settings.insights_db_name}"
            st.success(f"Connected · {target}")
        except Exception as exc:
            st.error(f"Not reachable: {exc}")

with col_sources:
    st.markdown("**Source systems** (read-only)")
    st.write(
        {
            "FleetMgmt MSSQL": "configured" if settings.fleetmgmt_mssql_password else "⚠ not configured",
            "KRAI PostgreSQL": "configured" if settings.krai_pg_password else "⚠ not configured",
            "Radix API": "configured" if settings.is_radix_configured else "⚠ not configured",
        }
    )

st.divider()
st.subheader("Business rules")
st.write(
    f"Warranty standard: **{settings.warranty_default_days} days** flat "
    f"(overrides in `{settings.warranty_rules_path}`)."
)
st.write(f"Customer mapping: `{settings.customer_mapping_path}`")

st.info(
    "Phase 1 / Repo-Bootstrap complete. Next up: ETL extractors → device matcher "
    "→ `insights.devices_unified`, then the Device-Inventory page."
)
