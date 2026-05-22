"""
Service-Qualität — Alarm-Aufkommen aus der Flotten-Verwaltung: auffällige Geräte
(defekte Sensoren / wiederkehrende Störungen), störanfällige Modelle, häufigste
Alarm-Codes und noch offene Alarme.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from insights.core.db import insights_engine
from sqlalchemy import text

EINSTUFUNG_LABEL = {
    "sensor_spam": "Sensor-Spam (sehr viele Alarme)",
    "erhoeht": "Erhöht",
    "normal": "Normal",
}


@st.cache_data(ttl=300)
def frame(sql: str, params: dict | None = None) -> pd.DataFrame:
    with insights_engine().connect() as conn:
        return pd.DataFrame(conn.execute(text(sql), params or {}).mappings().all())


@st.cache_data(ttl=300)
def kennzahlen() -> dict:
    with insights_engine().connect() as conn:
        problem = conn.execute(text("SELECT count(*) FROM insights.vw_problem_devices")).scalar()
        spam = conn.execute(
            text("SELECT count(*) FROM insights.vw_problem_devices WHERE einstufung = 'sensor_spam'")
        ).scalar()
        offen = conn.execute(text("SELECT count(*) FROM insights.vw_open_events_aging")).scalar()
    return {"problem": problem, "spam": spam, "offen": offen}


st.title("🚨 Service-Qualität")
st.caption(
    "Alarme der Drucksysteme aus der Flotten-Verwaltung (letzte 365 Tage). Hilft, "
    "auffällige Geräte und störanfällige Modelle früh zu erkennen — bevor der Kunde anruft."
)

k = kennzahlen()
c1, c2, c3 = st.columns(3)
c1.metric("Auffällige Geräte", f"{k['problem']:,}".replace(",", "."))
c2.metric("davon Sensor-Spam", f"{k['spam']:,}".replace(",", "."))
c3.metric("Offene Alarme", f"{k['offen']:,}".replace(",", "."))

st.divider()
tab_dev, tab_mod, tab_code, tab_open = st.tabs(
    ["Auffällige Geräte", "Störanfällige Modelle", "Häufigste Alarme", "Offene Alarme"]
)

with tab_dev:
    st.markdown("**Geräte mit auffällig vielen Alarmen** — mögliche defekte Sensoren oder wiederkehrende Störungen.")
    st.caption("Ab ~1 Alarm/Tag = erhöht, ab ~3 Alarme/Tag = Sensor-Spam. Gute Field-Service-Kandidaten.")
    nur_spam = st.checkbox("Nur Sensor-Spam anzeigen", value=False)
    such = st.text_input("Filter — Kunde (optional)", "", key="dev_q")
    clauses = ["einstufung = 'sensor_spam'"] if nur_spam else ["TRUE"]
    params: dict = {}
    if such.strip():
        clauses.append("customer_name ILIKE :q")
        params["q"] = f"%{such.strip()}%"
    df = frame(
        "SELECT customer_name, customer_city, manufacturer_canonical, model_display, device_serial, "
        "device_status, events_365d, offene_alarme, verschiedene_codes, einstufung, letzter_alarm "
        f"FROM insights.vw_problem_devices WHERE {' AND '.join(clauses)} LIMIT 500",
        params,
    )
    if not df.empty:
        df["einstufung"] = df["einstufung"].map(EINSTUFUNG_LABEL).fillna(df["einstufung"])
        df = df.rename(columns={
            "customer_name": "Kunde", "customer_city": "Ort", "manufacturer_canonical": "Hersteller",
            "model_display": "Modell", "device_serial": "Geräte-Seriennummer", "device_status": "Status",
            "events_365d": "Alarme (365 T)", "offene_alarme": "davon offen",
            "verschiedene_codes": "Verschiedene Codes", "einstufung": "Einstufung", "letzter_alarm": "Letzter Alarm",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Gerät(e)")
    st.dataframe(df, width="stretch", hide_index=True)

with tab_mod:
    st.markdown("**Störanfälligste Modelle** — Alarme je Gerät (ab 5 Geräten, damit der Wert aussagekräftig ist).")
    df = frame(
        "SELECT hersteller, modell, geraete, alarme_gesamt, alarme_pro_geraet "
        "FROM insights.vw_problem_models LIMIT 100"
    )
    if not df.empty:
        df = df.rename(columns={
            "hersteller": "Hersteller", "modell": "Modell", "geraete": "Geräte",
            "alarme_gesamt": "Alarme gesamt", "alarme_pro_geraet": "Ø Alarme/Gerät",
        })
    st.dataframe(df, width="stretch", hide_index=True)

with tab_code:
    st.markdown("**Häufigste Alarm-Codes der gesamten Flotte** mit Bedeutung und Anzahl betroffener Geräte.")
    st.caption("Viele betroffene Geräte = systemisches Thema; wenige Geräte bei hoher Zahl = ein lautes Gerät.")
    df = frame(
        "SELECT alert_code, bedeutung, alarme, betroffene_geraete, max_severity "
        "FROM insights.vw_top_alert_codes LIMIT 100"
    )
    if not df.empty:
        df = df.rename(columns={
            "alert_code": "Code", "bedeutung": "Bedeutung", "alarme": "Alarme",
            "betroffene_geraete": "Betroffene Geräte", "max_severity": "Max. Schweregrad",
        })
    st.dataframe(df, width="stretch", hide_index=True)

with tab_open:
    st.markdown("**Offene (noch nicht quittierte) Alarme** — älteste zuerst.")
    min_tage = int(st.number_input("Mindestens offen seit (Tage)", min_value=0, max_value=3650, value=0, step=7))
    such = st.text_input("Filter — Kunde (optional)", "", key="open_q")
    clauses = ["offen_tage >= :mt"]
    params = {"mt": min_tage}
    if such.strip():
        clauses.append("customer_name ILIKE :q")
        params["q"] = f"%{such.strip()}%"
    df = frame(
        "SELECT customer_name, customer_city, manufacturer_canonical, model_display, device_serial, "
        "device_status, alert_code, bedeutung, severity, offen_seit, offen_tage "
        f"FROM insights.vw_open_events_aging WHERE {' AND '.join(clauses)} ORDER BY offen_tage DESC LIMIT 500",
        params,
    )
    if not df.empty:
        df = df.rename(columns={
            "customer_name": "Kunde", "customer_city": "Ort", "manufacturer_canonical": "Hersteller",
            "model_display": "Modell", "device_serial": "Geräte-Seriennummer", "device_status": "Status",
            "alert_code": "Code", "bedeutung": "Bedeutung", "severity": "Schweregrad",
            "offen_seit": "Offen seit", "offen_tage": "Offen (Tage)",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " offene(r) Alarm(e) (max. 500)")
    st.dataframe(df, width="stretch", hide_index=True)
