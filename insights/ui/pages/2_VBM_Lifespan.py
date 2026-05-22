"""
VBM Lifespan page — real-life consumable yield vs OEM, false-report detection,
and serial-backed warranty / negotiation candidates.

Reads only insights.vw_vbm_lifecycle, vw_toner_yield_vs_oem, vw_premature_failures.
Phase 2: FleetMgmt ACCMARKERREFILL data (199k events).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from insights.core.db import insights_engine  # noqa: E402
from sqlalchemy import text  # noqa: E402


@st.cache_data(ttl=300)
def run(sql: str, params: dict | None = None) -> pd.DataFrame:
    with insights_engine().connect() as conn:
        return pd.DataFrame(conn.execute(text(sql), params or {}).mappings().all())


@st.cache_data(ttl=300)
def overview() -> dict:
    with insights_engine().connect() as conn:
        cls = dict(conn.execute(text(
            "SELECT classification, count(*) FROM insights.vw_vbm_lifecycle GROUP BY classification")).all())
        false_n = conn.execute(text(
            "SELECT count(*) FROM insights.vw_vbm_lifecycle WHERE likely_false_report")).scalar()
        fleet = conn.execute(text(
            "SELECT round(avg(avg_pct_of_oem), 1) FROM insights.vw_toner_yield_vs_oem WHERE refills >= 50")).scalar()
    return {"cls": cls, "false_n": false_n, "fleet": fleet}


st.set_page_config(page_title="VBM Lifespan · krai-insights", page_icon="🧪", layout="wide")
st.title("🧪 VBM Lifespan — Toner/Teile-Realität vs. OEM")
st.caption("Echte Standzeiten, Falschmeldungs-Erkennung und serial-belegte Garantie-Kandidaten (FleetMgmt).")

ov = overview()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Real-Wechsel (Serial)", f"{ov['cls'].get('real_new_cartridge', 0):,}")
c2.metric("Wiedereinsetzen", f"{ov['cls'].get('reinsert_same', 0):,}")
c3.metric("Falschmeldungs-Verdacht", f"{ov['false_n']:,}")
c4.metric("Flotte: Real vs OEM", f"{ov['fleet']} %" if ov["fleet"] else "—")

st.divider()
tab_yield, tab_warranty, tab_device = st.tabs(
    ["OEM vs Real (Yield)", "Garantie-Kandidaten", "Geräte-Toner-Historie"]
)

with tab_yield:
    colc, refc = st.columns([2, 1])
    colorant = colc.selectbox("Farbe", ["black", "cyan", "magenta", "yellow"], index=0)
    min_refills = int(refc.number_input("Min. Wechsel", min_value=10, max_value=2000, value=100, step=10))
    yld = run(
        "SELECT manufacturer_canonical, model_display, refills, devices, avg_real_pages, "
        "oem_target_pages, avg_pct_of_oem FROM insights.vw_toner_yield_vs_oem "
        "WHERE colorant = :c AND refills >= :n ORDER BY avg_pct_of_oem DESC",
        {"c": colorant, "n": min_refills},
    )
    st.write(f"**{len(yld)}** Modelle · Werte > 100 pct = reale Standzeit über OEM-Soll (Marge bei OEM-Kalkulation).")
    st.dataframe(yld, use_container_width=True, hide_index=True)

with tab_warranty:
    st.caption("Zyklen < 70 pct der OEM-Soll-Laufzeit — serial-belegte Kandidaten fürs Hersteller-Nachfassen.")
    mfr = st.text_input("Filter Hersteller/Kunde/Modell (optional)", "")
    sql = (
        "SELECT customer_name, model_display, device_serial, radix_device_number, colorant, "
        "cartridge_serial, real_pages, oem_target_pages, pct_of_oem, replaced_on "
        "FROM insights.vw_premature_failures WHERE cartridge_serial IS NOT NULL "
    )
    params: dict = {}
    if mfr.strip():
        sql += ("AND (manufacturer_canonical ILIKE :q OR customer_name ILIKE :q OR model_display ILIKE :q) ")
        params["q"] = f"%{mfr.strip()}%"
    sql += "ORDER BY pct_of_oem ASC LIMIT 500"
    warr = run(sql, params)
    st.write(f"**{len(warr)}** serial-belegte Kandidaten (max 500 gezeigt).")
    st.dataframe(warr, use_container_width=True, hide_index=True)

with tab_device:
    q = st.text_input("Gerät — Seriennummer oder Radix-ID", "")
    if q.strip():
        hist = run(
            "SELECT v.occurred_at::date AS datum, v.colorant, v.marker_name, v.cartridge_serial, "
            "v.classification, v.pages_since_previous AS real_pages, v.oem_target_pages, "
            "v.pct_of_oem, v.lifespan_rating, v.likely_false_report "
            "FROM insights.vw_vbm_lifecycle v "
            "JOIN insights.devices_unified d ON d.fleetmgmt_device_id = v.fleetmgmt_device_id "
            "WHERE d.manufacturer_serial = :q OR d.radix_device_number = :q "
            "ORDER BY v.occurred_at DESC LIMIT 200",
            {"q": q.strip()},
        )
        st.write(f"**{len(hist)}** VBM-Events")
        st.dataframe(hist, use_container_width=True, hide_index=True)
    else:
        st.info("Seriennummer oder Radix-Geräte-ID eingeben, um die Toner-/Teile-Historie zu sehen.")
