"""Übersichtsseite — Kurzbeschreibung, zentrale Kennzahlen und Systemstatus."""

from __future__ import annotations

import streamlit as st
from insights.core.config import get_settings
from insights.core.db import insights_engine
from sqlalchemy import text

settings = get_settings()

st.title("📊 KRAI Insights")
st.caption("Auswertungen rund um Drucksysteme, Verbrauchsmaterial, Garantie und Service.")

st.markdown(
    "Diese Anwendung führt Daten aus der Flotten-Verwaltung und dem Service-System "
    "in einer gemeinsamen Auswertungs-Datenbank zusammen. Über die Navigation links "
    "stehen folgende Bereiche zur Verfügung:"
)
st.markdown(
    "- **Geräte-Inventar** — alle erfassten Drucksysteme mit Standort, Kunde und Meldestatus.\n"
    "- **Verbrauchsmaterial** — echte Toner-/Teile-Standzeiten im Vergleich zur Hersteller-Angabe "
    "sowie Garantie-Bewertungen."
)

st.divider()
st.subheader("Zentrale Kennzahlen")


@st.cache_data(ttl=300)
def kennzahlen() -> dict:
    out: dict[str, int | None] = {}
    try:
        with insights_engine().connect() as conn:
            out["geraete"] = conn.execute(text("SELECT count(*) FROM insights.devices_unified")).scalar()
            out["aktiv"] = conn.execute(
                text("SELECT count(*) FROM insights.devices_unified WHERE device_status = 'live'")
            ).scalar()
            out["material_events"] = conn.execute(
                text("SELECT count(*) FROM insights.vbm_lifecycle_events")
            ).scalar()
            out["garantie"] = conn.execute(
                text("SELECT count(*) FROM insights.vw_warranty_assessment WHERE warranty_class = 'claim'")
            ).scalar()
    except Exception:
        return {}
    return out


k = kennzahlen()
if k:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Drucksysteme gesamt", f"{k.get('geraete', 0):,}".replace(",", "."))
    c2.metric("Aktiv (meldet)", f"{k.get('aktiv', 0):,}".replace(",", "."))
    c3.metric("Material-Wechsel erfasst", f"{k.get('material_events', 0):,}".replace(",", "."))
    c4.metric("Mögliche Garantiefälle", f"{k.get('garantie', 0):,}".replace(",", "."))
else:
    st.info("Kennzahlen derzeit nicht verfügbar — bitte Datenbank-Verbindung prüfen.")

st.divider()
st.subheader("Systemstatus")
col_db, col_quellen = st.columns(2)

with col_db:
    st.markdown("**Auswertungs-Datenbank**")
    try:
        with insights_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        st.success("Verbunden")
    except Exception:
        st.error("Nicht erreichbar")

with col_quellen:
    st.markdown("**Datenquellen** (nur lesend)")
    st.write(
        {
            "Flotten-Verwaltung": "verbunden" if settings.fleetmgmt_mssql_password else "nicht konfiguriert",
            "Service-System (Radix)": "verbunden" if settings.is_radix_configured else "nicht konfiguriert",
            "Wissens-Datenbank (KRAI)": "verbunden" if settings.krai_pg_password else "nicht konfiguriert",
        }
    )
