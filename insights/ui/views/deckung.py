"""
Deckung & Kalkulation — reale Druck-Deckung je Kunde (Klickpreis-Nachberechnung)
und Entwicklereinheit-Frühausfälle bei hoher Deckung (HP-Risiko, für den Service).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from insights.core.db import insights_engine
from insights.ui.links import doc
from sqlalchemy import text


@st.cache_data(ttl=300)
def frame(sql: str, params: dict | None = None) -> pd.DataFrame:
    with insights_engine().connect() as conn:
        return pd.DataFrame(conn.execute(text(sql), params or {}).mappings().all())


@st.cache_data(ttl=300)
def kennzahlen() -> dict:
    with insights_engine().connect() as conn:
        ueber6 = conn.execute(
            text("SELECT count(*) FROM insights.vw_coverage_by_customer WHERE ueber_klickpreis_6pct")
        ).scalar()
        kunden = conn.execute(text("SELECT count(*) FROM insights.vw_coverage_by_customer")).scalar()
        ent = conn.execute(text("SELECT count(*) FROM insights.vw_developer_unit_risk")).scalar()
    return {"ueber6": ueber6, "kunden": kunden, "ent": ent}


st.title("📈 Deckung & Kalkulation")
st.caption(
    "Reale Druck-Deckung (Tonerfläche pro Seite) je Kunde und Gerät. Der Klickpreis "
    "kalkuliert mit ~6 % Deckung — Kunden darüber verbrauchen mehr Toner als berechnet."
)
st.caption(f"📖 Methodik (Klickpreis-6 %, Entwickler-Risiko): [Doku Deckung]({doc('deckung.md')}) · "
           f"[Garantie/Deckungskorrektur]({doc('garantie.md', '1-wann-ist-etwas-ein-garantiefall')})")

k = kennzahlen()
c1, c2, c3 = st.columns(3)
c1.metric("Kunden über 6 % Deckung", f"{k['ueber6']:,}".replace(",", "."),
          help="Über der Klickpreis-Annahme (6 %) → Nachberechnung prüfen.")
c2.metric("Kunden mit Deckungsdaten", f"{k['kunden']:,}".replace(",", "."))
c3.metric("Entwickler-Frühausfälle", f"{k['ent']:,}".replace(",", "."),
          help="Entwicklereinheiten, die innerhalb 1 Jahr erneut getauscht wurden.")

st.divider()
tab_kunde, tab_ent = st.tabs(["Kunden über Klickpreis-Deckung", "Entwickler-Risiko (hohe Deckung)"])

with tab_kunde:
    st.markdown("**Reale Deckung je Kunde** (seitengewichtet). Über 6 % = mehr Tonerverbrauch als "
                "im Klickpreis kalkuliert → Kandidat für Nachberechnung / Vertragsanpassung.")
    schwelle = st.slider("Mindest-Deckung % anzeigen", min_value=0, max_value=20, value=6, step=1)
    df = frame(
        "SELECT customer_name, customer_city, geraete, gedruckte_seiten, avg_deckung_pct "
        "FROM insights.vw_coverage_by_customer WHERE avg_deckung_pct >= :s ORDER BY avg_deckung_pct DESC LIMIT 500",
        {"s": schwelle},
    )
    if not df.empty:
        df = df.rename(columns={
            "customer_name": "Kunde", "customer_city": "Ort", "geraete": "Geräte",
            "gedruckte_seiten": "Gedruckte Seiten", "avg_deckung_pct": "Ø Deckung %",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + f" Kunde(n) ≥ {schwelle} % Deckung")
    st.dataframe(df, width="stretch", hide_index=True)

with tab_ent:
    st.markdown("**Entwicklereinheit-Frühausfälle und die Deckung des Geräts.** Laut HP gerät bei "
                "Deckung über ~5 % die Toner/Entwickler-Mischung aus der Balance → Entwickler gehen "
                "früher kaputt. Hohe Deckung + Frühausfall = wahrscheinlich genau dieser Effekt.")
    nur_hoch = st.checkbox("Nur mit belegter Deckung über 5 %", value=False)
    clause = "WHERE deckung_ueber_5pct" if nur_hoch else "WHERE TRUE"
    df = frame(
        "SELECT customer_name, manufacturer_canonical, model_display, device_serial, radix_device_number, "
        "entwicklereinheit, einbau_datum, erneut_getauscht, standzeit_tage, standzeit_seiten, "
        "avg_deckung_pct, diagnose "
        f"FROM insights.vw_developer_unit_risk {clause} "
        "ORDER BY avg_deckung_pct DESC NULLS LAST, standzeit_tage ASC LIMIT 500"
    )
    if not df.empty:
        df = df.rename(columns={
            "customer_name": "Kunde", "manufacturer_canonical": "Hersteller", "model_display": "Modell",
            "device_serial": "Geräte-Seriennummer", "radix_device_number": "Radix-ID",
            "entwicklereinheit": "Entwicklereinheit", "einbau_datum": "Eingebaut",
            "erneut_getauscht": "Erneut getauscht", "standzeit_tage": "Standzeit (Tage)",
            "standzeit_seiten": "Standzeit (Seiten)", "avg_deckung_pct": "Ø Deckung % (Gerät)",
            "diagnose": "Diagnose/Symptom",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Entwickler-Frühausfall/-ausfälle")
    st.caption("Hinweis: die Geräte-Deckung ist leer, wo keine Deckungsdaten am Gerät vorliegen.")
    st.dataframe(df, width="stretch", hide_index=True)
