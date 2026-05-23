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
        geraete6 = conn.execute(
            text("SELECT count(*) FROM insights.vw_device_coverage WHERE avg_deckung_pct > 6")
        ).scalar()
        ent = conn.execute(text("SELECT count(*) FROM insights.vw_developer_unit_risk")).scalar()
    return {"ueber6": ueber6, "kunden": kunden, "geraete6": geraete6, "ent": ent}


st.title("📈 Deckung & Kalkulation")
st.caption(
    "Reale Druck-Deckung (Tonerfläche pro Seite) je Kunde und Gerät. Der Klickpreis "
    "kalkuliert mit ~6 % Deckung — Kunden darüber verbrauchen mehr Toner als berechnet."
)
st.caption(f"📖 Methodik (Klickpreis-6 %, Entwickler-Risiko): [Doku Deckung]({doc('deckung.md')}) · "
           f"[Garantie/Deckungskorrektur]({doc('garantie.md', '1-wann-ist-etwas-ein-garantiefall')})")

k = kennzahlen()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Geräte über 6 % Deckung", f"{k['geraete6']:,}".replace(",", "."),
          help="Einzelne Geräte über der Klickpreis-Annahme — siehe Tab Geräte über Klickpreis-Deckung.")
c2.metric("Kunden über 6 % Deckung", f"{k['ueber6']:,}".replace(",", "."),
          help="Kunden, deren Flotten-Schnitt über 6 % liegt → Nachberechnung prüfen.")
c3.metric("Kunden mit Deckungsdaten", f"{k['kunden']:,}".replace(",", "."))
c4.metric("Entwickler-Frühausfälle", f"{k['ent']:,}".replace(",", "."),
          help="Entwicklereinheiten, die innerhalb 1 Jahr erneut getauscht wurden.")

st.divider()
tab_geraet, tab_kunde, tab_ent = st.tabs(
    ["Geräte über Klickpreis-Deckung", "Kunden über Klickpreis-Deckung", "Entwickler-Risiko (hohe Deckung)"]
)

with tab_geraet:
    st.markdown("**Reale Deckung je Gerät** (seitengewichtet). Genau hier sieht man, welche "
                "**einzelnen Geräte** über der Klickpreis-Annahme (6 %) drucken — mit Radix-ID zur "
                "Zuordnung. Sortiert nach Deckung absteigend.")
    schwelle_g = st.slider("Mindest-Deckung % anzeigen", min_value=0, max_value=20, value=6, step=1,
                           key="schwelle_geraet")
    dfg = frame(
        "SELECT customer_name, customer_city, manufacturer_canonical, model_display, "
        "device_serial, radix_device_number, gedruckte_seiten, avg_deckung_pct "
        "FROM insights.vw_device_coverage WHERE avg_deckung_pct >= :s "
        "ORDER BY avg_deckung_pct DESC LIMIT 1000",
        {"s": schwelle_g},
    )
    if not dfg.empty:
        dfg = dfg.rename(columns={
            "customer_name": "Kunde", "customer_city": "Ort",
            "manufacturer_canonical": "Hersteller", "model_display": "Modell",
            "device_serial": "Geräte-Seriennummer", "radix_device_number": "Radix-ID",
            "gedruckte_seiten": "Gedruckte Seiten", "avg_deckung_pct": "Ø Deckung %",
        })
    st.write(f"**{len(dfg):,}**".replace(",", ".") + f" Gerät(e) ≥ {schwelle_g} % Deckung "
             "(nur Geräte mit ≥ 500 erfassten Seiten)")
    st.dataframe(dfg, width="stretch", hide_index=True)
    st.caption("Spalten sind sortierbar (Klick auf den Kopf). Belastbarkeit steigt mit der Seitenzahl: "
               "**Werte um 100 % bei wenigen Seiten** stammen oft aus einzelnen verrauschten/gedeckelten "
               "Messungen (Deckung wird auf 0,5 bis 100 % begrenzt) — für eine Nachberechnung Geräte mit "
               "hoher Seitenzahl bevorzugen.")

with tab_kunde:
    st.markdown("**Reale Deckung je Kunde** (seitengewichtet über die ganze Flotte des Kunden). Über "
                "6 % = mehr Tonerverbrauch als im Klickpreis kalkuliert → Kandidat für Nachberechnung "
                "/ Vertragsanpassung. Geräte-genau siehe Tab nebenan.")
    schwelle = st.slider("Mindest-Deckung % anzeigen", min_value=0, max_value=20, value=6, step=1,
                         key="schwelle_kunde")
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
