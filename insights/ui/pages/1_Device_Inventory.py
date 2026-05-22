"""
Device-Inventory page — searchable view over insights.devices_unified.

Reads only `insights.vw_device_lookup` (the device_lookup route's view). Search
by serial / Radix device id / customer / model; filter by telemetry status.
Phase 1: FleetMgmt data; Radix enrichment (Radix id, OEM code, contract) follows.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running via `streamlit run` from the repo root without install.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from insights.core.db import insights_engine  # noqa: E402
from sqlalchemy import text  # noqa: E402

_STATUSES = ["live", "silent", "never_reported", "deactivated", "deleted"]


@st.cache_data(ttl=300)
def load_overview() -> tuple[int, dict[str, int]]:
    with insights_engine().connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM insights.vw_device_lookup")).scalar() or 0
        by_status = dict(
            conn.execute(
                text("SELECT device_status, count(*) FROM insights.vw_device_lookup GROUP BY device_status")
            ).all()
        )
    return total, by_status


@st.cache_data(ttl=300)
def query_devices(search: str, statuses: list[str], limit: int) -> pd.DataFrame:
    clauses = ["1=1"]
    params: dict[str, object] = {}
    if search:
        clauses.append(
            "AND (manufacturer_serial ILIKE :q OR radix_device_number ILIKE :q "
            "OR customer_name ILIKE :q OR model_display ILIKE :q "
            "OR CAST(fleetmgmt_device_id AS TEXT) = :exact)"
        )
        params["q"] = f"%{search}%"
        params["exact"] = search
    if statuses:
        clauses.append("AND device_status = ANY(:statuses)")
        params["statuses"] = statuses
    params["lim"] = limit
    sql = (
        "SELECT manufacturer_serial, radix_device_number, fleetmgmt_device_id, internal_id, "
        "customer_name, customer_city, manufacturer_canonical, model_display, "
        "device_status, telemetry_stale_days, last_data_transfer_at "
        "FROM insights.vw_device_lookup "
        f"WHERE {' '.join(clauses)} "
        "ORDER BY (device_status = 'live') DESC, customer_name NULLS LAST "
        "LIMIT :lim"
    )
    with insights_engine().connect() as conn:
        return pd.DataFrame(conn.execute(text(sql), params).mappings().all())


st.set_page_config(page_title="Device Inventory · krai-insights", page_icon="🖨️", layout="wide")
st.title("🖨️ Device Inventory")
st.caption("Fused device registry over `insights.devices_unified` — FleetMgmt (Radix enrichment pending).")

total, by_status = load_overview()
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total", f"{total:,}")
c2.metric("Live (≤60d)", f"{by_status.get('live', 0):,}")
c3.metric("Silent (>60d)", f"{by_status.get('silent', 0):,}")
c4.metric("Never reported", f"{by_status.get('never_reported', 0):,}")
c5.metric("Deactivated/Deleted", f"{by_status.get('deactivated', 0) + by_status.get('deleted', 0):,}")

st.divider()
col_search, col_status, col_limit = st.columns([3, 2, 1])
search = col_search.text_input("Search — serial / Radix-ID / customer / model", "")
statuses = col_status.multiselect("Status", _STATUSES, default=["live", "silent", "never_reported"])
limit = int(col_limit.number_input("Max rows", min_value=50, max_value=5000, value=500, step=50))

df = query_devices(search.strip(), statuses, limit)
st.write(f"**{len(df):,}** device(s) shown")
st.dataframe(df, use_container_width=True, hide_index=True)

if not df.empty and "device_status" in df:
    silent = df[df["device_status"].isin(["silent", "never_reported"])]
    if len(silent):
        st.warning(
            f"⚠️ {len(silent):,} of the shown devices report no current data "
            "(silent/never reported) — likely collector offline / server swap / network. "
            "Check on-site before relying on counters."
        )
