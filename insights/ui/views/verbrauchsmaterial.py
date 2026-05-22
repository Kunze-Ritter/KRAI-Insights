"""
Verbrauchsmaterial — echte Standzeiten von Toner und Teilen, Vergleich zur
Hersteller-Angabe und Garantie-Bewertung.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from insights.core.db import insights_engine
from sqlalchemy import text

WARRANTY_LABEL = {
    "claim": "Garantiefall",
    "negotiation": "Verhandlungs-Kandidat",
    "wear": "Verschleiß (normal)",
    "normal": "Normal",
    "artifact": "Messartefakt",
    "unknown": "Unbekannt",
}
CLASS_LABEL = {
    "real_new_cartridge": "Echter Wechsel",
    "reinsert_same": "Wiedereingesetzt",
    "no_serial": "Ohne Seriennummer",
}


@st.cache_data(ttl=300)
def kennzahlen() -> dict:
    with insights_engine().connect() as conn:
        cls = dict(
            conn.execute(
                text("SELECT classification, count(*) FROM insights.vw_vbm_lifecycle GROUP BY classification")
            ).all()
        )
        flott = conn.execute(
            text("SELECT round(avg(avg_pct_of_oem)) FROM insights.vw_toner_yield_vs_oem WHERE refills >= 50")
        ).scalar()
        garantie = dict(
            conn.execute(
                text("SELECT warranty_class, count(*) FROM insights.vw_warranty_assessment GROUP BY warranty_class")
            ).all()
        )
    return {"cls": cls, "flott": flott, "garantie": garantie}


@st.cache_data(ttl=300)
def frame(sql: str, params: dict | None = None) -> pd.DataFrame:
    with insights_engine().connect() as conn:
        return pd.DataFrame(conn.execute(text(sql), params or {}).mappings().all())


st.title("🧪 Verbrauchsmaterial — Standzeiten & Garantie")
st.caption(
    "Verbrauchsmaterial (Toner, Trommeln, Wartungsteile): wie lange ein Teil tatsächlich "
    "gehalten hat, im Vergleich zur Hersteller-Angabe — als Grundlage für Kalkulation und Garantie."
)

k = kennzahlen()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Echte Wechsel (mit Seriennummer)", f"{k['cls'].get('real_new_cartridge', 0):,}".replace(",", "."))
c2.metric("Wiedereingesetzt", f"{k['cls'].get('reinsert_same', 0):,}".replace(",", "."))
c3.metric("Standzeit vs. Hersteller-Soll", f"{int(k['flott'])} %" if k["flott"] else "—")
c4.metric("Mögliche Garantiefälle", f"{k['garantie'].get('claim', 0):,}".replace(",", "."))

st.divider()
tab_yield, tab_garantie, tab_geraet = st.tabs(
    ["Standzeit vs. Hersteller-Soll", "Garantie-Bewertung", "Verlauf je Gerät"]
)

with tab_yield:
    st.markdown("**Durchschnittliche Toner-Standzeit je Modell im Vergleich zur Hersteller-Angabe.**")
    st.caption(
        "Werte über 100 % bedeuten: Das Material hält in der Praxis länger als vom Hersteller angegeben. "
        "Das ist für die Vertragskalkulation relevant."
    )
    colc, refc = st.columns([2, 1])
    farbe = colc.selectbox("Farbe", ["black", "cyan", "magenta", "yellow"],
                           index=0, format_func=lambda c: {"black": "Schwarz", "cyan": "Cyan",
                                                            "magenta": "Magenta", "yellow": "Gelb"}.get(c, c))
    min_wechsel = int(refc.number_input("Mindestanzahl Wechsel", min_value=10, max_value=2000, value=100, step=10))
    df = frame(
        "SELECT manufacturer_canonical, model_display, refills, devices, avg_real_pages, "
        "oem_target_pages, avg_pct_of_oem FROM insights.vw_toner_yield_vs_oem "
        "WHERE colorant = :c AND refills >= :n ORDER BY avg_pct_of_oem DESC",
        {"c": farbe, "n": min_wechsel},
    )
    if not df.empty:
        df = df.rename(columns={
            "manufacturer_canonical": "Hersteller", "model_display": "Modell", "refills": "Wechsel",
            "devices": "Geräte", "avg_real_pages": "Ø echte Seiten",
            "oem_target_pages": "Hersteller-Soll (Seiten)", "avg_pct_of_oem": "Ø % vom Soll",
        })
    st.dataframe(df, width="stretch", hide_index=True)

with tab_garantie:
    st.markdown("**Garantie-Bewertung je Material-Lebenszyklus (Zeit und Laufleistung).**")
    st.caption(
        "Garantiefall = innerhalb 1 Jahr und deutlich unter Soll-Laufleistung. "
        "Verhandlungs-Kandidat = älter als 1 Jahr, aber ebenfalls unter Soll. "
        "Jeder Eintrag ist über die Material-Seriennummer belegt."
    )
    bewertung = st.multiselect(
        "Bewertung", options=["claim", "negotiation"], default=["claim", "negotiation"],
        format_func=lambda w: WARRANTY_LABEL.get(w, w),
    )
    such = st.text_input("Filter — Kunde, Hersteller oder Modell (optional)", "")
    clauses = ["cartridge_serial IS NOT NULL"]
    params: dict = {}
    if bewertung:
        clauses.append("warranty_class = ANY(:cls)")
        params["cls"] = bewertung
    if such.strip():
        clauses.append("(customer_name ILIKE :q OR manufacturer_canonical ILIKE :q OR model_display ILIKE :q)")
        params["q"] = f"%{such.strip()}%"
    df = frame(
        "SELECT customer_name, manufacturer_canonical, model_display, device_serial, radix_device_number, "
        "colorant, cartridge_serial, installed_on, removed_on, age_days, pages, rated, pct_of_oem, warranty_class "
        f"FROM insights.vw_warranty_assessment WHERE {' AND '.join(clauses)} "
        "ORDER BY pct_of_oem ASC LIMIT 500",
        params,
    )
    if not df.empty:
        df["warranty_class"] = df["warranty_class"].map(WARRANTY_LABEL).fillna(df["warranty_class"])
        df = df.rename(columns={
            "customer_name": "Kunde", "manufacturer_canonical": "Hersteller", "model_display": "Modell",
            "device_serial": "Geräte-Seriennummer", "radix_device_number": "Radix-ID", "colorant": "Farbe",
            "cartridge_serial": "Material-Seriennummer", "installed_on": "Eingebaut", "removed_on": "Gewechselt",
            "age_days": "Standzeit (Tage)", "pages": "Gelaufene Seiten", "rated": "Hersteller-Soll",
            "pct_of_oem": "% vom Soll", "warranty_class": "Bewertung",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Eintrag/Einträge (max. 500)")
    st.dataframe(df, width="stretch", hide_index=True)

with tab_geraet:
    st.markdown("**Material-Verlauf eines einzelnen Geräts.**")
    q = st.text_input("Gerät — Seriennummer oder Radix-ID", "")
    if q.strip():
        df = frame(
            "SELECT v.occurred_at::date AS datum, v.colorant, v.marker_name, v.cartridge_serial, "
            "v.classification, v.pages_since_previous, v.oem_target_pages, v.pct_of_oem, "
            "v.lifespan_rating, v.likely_false_report "
            "FROM insights.vw_vbm_lifecycle v "
            "JOIN insights.devices_unified d ON d.fleetmgmt_device_id = v.fleetmgmt_device_id "
            "WHERE d.manufacturer_serial = :q OR d.radix_device_number = :q "
            "ORDER BY v.occurred_at DESC LIMIT 200",
            {"q": q.strip()},
        )
        if not df.empty:
            df["classification"] = df["classification"].map(CLASS_LABEL).fillna(df["classification"])
            df["likely_false_report"] = df["likely_false_report"].map({True: "ja", False: "nein"})
            df = df.rename(columns={
                "datum": "Datum", "colorant": "Farbe", "marker_name": "Material",
                "cartridge_serial": "Material-Seriennummer", "classification": "Art",
                "pages_since_previous": "Gelaufene Seiten", "oem_target_pages": "Hersteller-Soll",
                "pct_of_oem": "% vom Soll", "lifespan_rating": "Standzeit-Klasse",
                "likely_false_report": "Falschmeldungs-Verdacht",
            })
        st.write(f"**{len(df):,}**".replace(",", ".") + " Material-Ereignis(se)")
        st.dataframe(df, width="stretch", hide_index=True)
    else:
        st.info("Seriennummer oder Radix-ID eingeben, um den Material-Verlauf des Geräts anzuzeigen.")
