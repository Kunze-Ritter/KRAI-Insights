"""
Kosten & Verträge — Material- und Arbeitskosten aus dem Service-System sowie
Vertragslaufzeiten (auslaufende Verträge, Geräte ohne Vertrag).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from insights.core.db import insights_engine
from sqlalchemy import text

COST_TYPE_LABEL = {"material": "Material", "labor": "Arbeit"}


@st.cache_data(ttl=300)
def frame(sql: str, params: dict | None = None) -> pd.DataFrame:
    with insights_engine().connect() as conn:
        return pd.DataFrame(conn.execute(text(sql), params or {}).mappings().all())


st.title("💶 Kosten & Verträge")
st.caption(
    "Material- und Arbeitskosten aus dem Service-System sowie Vertragslaufzeiten. "
    "Vertrag = vertraglich gedeckt, Aufwand = berechenbar, Garantie = auf Garantie."
)

tab_struktur, tab_kunde, tab_vertraege = st.tabs(
    ["Kostenstruktur", "Kosten je Kunde", "Verträge"]
)

with tab_struktur:
    st.markdown("**Kosten nach Abrechnungsart** (Material in €, Arbeit in Stunden).")
    df = frame(
        "SELECT invoicing_type, cost_type, lines, material_eur, labor_hours "
        "FROM insights.vw_cost_by_invoicing ORDER BY lines DESC"
    )
    if not df.empty:
        df["cost_type"] = df["cost_type"].map(COST_TYPE_LABEL).fillna(df["cost_type"])
        df = df.rename(columns={
            "invoicing_type": "Abrechnungsart", "cost_type": "Art", "lines": "Positionen",
            "material_eur": "Material €", "labor_hours": "Arbeit (Std.)",
        })
    st.dataframe(df, width="stretch", hide_index=True)

with tab_kunde:
    st.markdown("**Kosten je Kunde** — Material und Arbeit, aufgeteilt nach berechenbar und Vertrag.")
    such = st.text_input("Kunde suchen (optional)", "")
    sql = (
        "SELECT customer_name, material_eur, billable_material_eur, contract_material_eur, "
        "labor_hours, material_lines, labor_lines FROM insights.vw_cost_by_customer "
        "WHERE customer_name IS NOT NULL "
    )
    params: dict = {}
    if such.strip():
        sql += "AND customer_name ILIKE :q "
        params["q"] = f"%{such.strip()}%"
    sql += "ORDER BY material_eur DESC NULLS LAST LIMIT 500"
    df = frame(sql, params)
    if not df.empty:
        df = df.rename(columns={
            "customer_name": "Kunde", "material_eur": "Material €",
            "billable_material_eur": "davon berechenbar €", "contract_material_eur": "davon Vertrag €",
            "labor_hours": "Arbeit (Std.)", "material_lines": "Material-Pos.", "labor_lines": "Arbeits-Pos.",
        })
    st.dataframe(df, width="stretch", hide_index=True)

with tab_vertraege:
    st.markdown("**Auslaufende Verträge** (nächste 90 Tage, ohne automatische Verlängerung).")
    df = frame(
        "SELECT customer_name, model_display, device_serial, code, contract_type, valid_until "
        "FROM insights.vw_contract_renewal_radar ORDER BY valid_until LIMIT 500"
    )
    if not df.empty:
        df = df.rename(columns={
            "customer_name": "Kunde", "model_display": "Modell", "device_serial": "Seriennummer",
            "code": "Vertrag-Nr.", "contract_type": "Vertragsart", "valid_until": "Läuft aus",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " auslaufende(r) Vertrag/Verträge")
    st.dataframe(df, width="stretch", hide_index=True)

    st.markdown("**Aktive Geräte ohne laufenden Vertrag** (Vertriebs-Chance).")
    df2 = frame(
        "SELECT customer_name, model_display, device_serial, manufacturer_canonical "
        "FROM insights.vw_out_of_contract_devices ORDER BY customer_name LIMIT 500"
    )
    if not df2.empty:
        df2 = df2.rename(columns={
            "customer_name": "Kunde", "model_display": "Modell", "device_serial": "Seriennummer",
            "manufacturer_canonical": "Hersteller",
        })
    st.write(f"**{len(df2):,}**".replace(",", ".") + " Gerät(e) ohne Vertrag")
    st.dataframe(df2, width="stretch", hide_index=True)
