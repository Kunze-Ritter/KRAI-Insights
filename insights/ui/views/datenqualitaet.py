"""
Datenqualität & Abgleich — Flotten-Verwaltung gegen Service-System (Radix)
gegenprüfen: Abrechnungs-Risiko (Schätz- statt Echt-Zähler), Flotten-Abgleich,
validierte Teilewechsel und die Frage, wo ein gebuchter Toner wirklich eingebaut wurde.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from insights.core.db import insights_engine
from sqlalchemy import text

VALID_LABEL = {
    "radix_geraet": "Radix bestätigt (gleiches Gerät)",
    "radix_kunde": "Radix bestätigt (gleicher Kunde)",
    "verdacht_fake": "Fake-Verdacht (kein Radix-Material)",
    "nur_fleet": "Nur Flotten-Verwaltung",
}
EINBAU_LABEL = {
    "korrekt": "Korrekt am gebuchten Gerät",
    "woanders_eingebaut": "Woanders eingebaut (Falschbuchung)",
    "kein_einbau_gefunden": "Kein Einbau gefunden",
}
ABGLEICH_LABEL = {
    "abweichung": "Abweichung (prüfen)",
    "teilweise": "Ähnlich (wahrscheinlich gleich)",
    "uebereinstimmung": "Übereinstimmung",
}
EINORDNUNG_LABEL = {
    "aktiv_unter_vertrag": "Aktiv, unter Vertrag",
    "aktiv_ohne_vertrag": "Aktiv, ohne Vertrag",
    "still_unter_vertrag": "Still, unter Vertrag",
    "still_ohne_vertrag": "Still, ohne Vertrag",
    "inaktiv": "Inaktiv",
}


@st.cache_data(ttl=300)
def frame(sql: str, params: dict | None = None) -> pd.DataFrame:
    with insights_engine().connect() as conn:
        return pd.DataFrame(conn.execute(text(sql), params or {}).mappings().all())


@st.cache_data(ttl=300)
def kennzahlen() -> dict:
    with insights_engine().connect() as conn:
        risiko = conn.execute(text("SELECT count(*) FROM insights.vw_billing_risk")).scalar()
        fake = conn.execute(
            text("SELECT count(*) FROM insights.vw_vbm_validation WHERE validierung = 'verdacht_fake'")
        ).scalar()
        woanders = conn.execute(
            text("SELECT count(*) FROM insights.vw_material_install_check WHERE einbau_status = 'woanders_eingebaut'")
        ).scalar()
        kunde_abw = conn.execute(
            text("SELECT count(*) FROM insights.vw_customer_device_mismatch WHERE abgleich = 'abweichung'")
        ).scalar()
    return {"risiko": risiko, "fake": fake, "woanders": woanders, "kunde_abw": kunde_abw}


st.title("🔍 Datenqualität & Abgleich")
st.caption(
    "Flotten-Verwaltung und Service-System gegeneinander prüfen — für saubere Abrechnung, "
    "korrekte Geräte-Zuordnung und weniger Toner-Fehlversand."
)

k = kennzahlen()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Abrechnungs-Risiko (Geräte)", f"{k['risiko']:,}".replace(",", "."))
c2.metric("Teilewechsel mit Fake-Verdacht", f"{k['fake']:,}".replace(",", "."))
c3.metric("Toner woanders eingebaut", f"{k['woanders']:,}".replace(",", "."))
c4.metric("Kunden-Abweichung (Geräte)", f"{k['kunde_abw']:,}".replace(",", "."))

st.divider()
tab_risk, tab_recon, tab_vbm, tab_einbau, tab_kunde = st.tabs(
    ["Abrechnungs-Risiko", "Flotten-Abgleich", "Teilewechsel-Validierung", "Material-Einbau", "Kunden-Abgleich"]
)

with tab_risk:
    st.markdown("**Geräte unter Vertrag, die keine Daten mehr melden** — die Abrechnung läuft auf Schätz-Zählern.")
    such = st.text_input("Filter — Kunde (optional)", "", key="risk_q")
    clauses = ["TRUE"]
    params: dict = {}
    if such.strip():
        clauses.append("customer_name ILIKE :q")
        params["q"] = f"%{such.strip()}%"
    df = frame(
        "SELECT customer_name, customer_city, manufacturer_canonical, model_display, device_serial, "
        "device_status, telemetry_stale_days, contract_end "
        f"FROM insights.vw_billing_risk WHERE {' AND '.join(clauses)} "
        "ORDER BY telemetry_stale_days DESC NULLS LAST LIMIT 500",
        params,
    )
    if not df.empty:
        df = df.rename(columns={
            "customer_name": "Kunde", "customer_city": "Ort", "manufacturer_canonical": "Hersteller",
            "model_display": "Modell", "device_serial": "Geräte-Seriennummer", "device_status": "Status",
            "telemetry_stale_days": "Tage ohne Meldung", "contract_end": "Vertrag bis",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Gerät(e) (max. 500)")
    st.dataframe(df, width="stretch", hide_index=True)

with tab_recon:
    st.markdown("**Flotten-Abgleich** — Meldestatus, Vertrag und Vorhandensein im Service-System je Gerät.")
    st.caption("Eine Wahrheit pro Gerät: Ist es aktiv? Steht es unter Vertrag? Ist es in Radix bekannt?")
    optionen = list(EINORDNUNG_LABEL.keys())
    auswahl = st.multiselect(
        "Einordnung", options=optionen, default=optionen, format_func=lambda v: EINORDNUNG_LABEL.get(v, v)
    )
    such = st.text_input("Filter — Kunde (optional)", "", key="recon_q")
    clauses = ["einordnung = ANY(:sel)"]
    params = {"sel": auswahl or optionen}
    if such.strip():
        clauses.append("customer_name ILIKE :q")
        params["q"] = f"%{such.strip()}%"
    df = frame(
        "SELECT customer_name, customer_city, manufacturer_canonical, model_display, device_serial, "
        "device_status, contract_active, contract_end, in_radix, einordnung "
        f"FROM insights.vw_fleet_reconciliation WHERE {' AND '.join(clauses)} "
        "ORDER BY customer_name LIMIT 1000",
        params,
    )
    if not df.empty:
        df["einordnung"] = df["einordnung"].map(EINORDNUNG_LABEL).fillna(df["einordnung"])
        df["contract_active"] = df["contract_active"].map({True: "ja", False: "nein"})
        df["in_radix"] = df["in_radix"].map({True: "ja", False: "nein"})
        df = df.rename(columns={
            "customer_name": "Kunde", "customer_city": "Ort", "manufacturer_canonical": "Hersteller",
            "model_display": "Modell", "device_serial": "Geräte-Seriennummer", "device_status": "Status",
            "contract_active": "Vertrag aktiv", "contract_end": "Vertrag bis", "in_radix": "In Radix",
            "einordnung": "Einordnung",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Gerät(e) (max. 1000)")
    st.dataframe(df, width="stretch", hide_index=True)

with tab_vbm:
    st.markdown("**Teilewechsel-Validierung** — meldet die Flotten-Verwaltung einen Wechsel, der im Service-System "
                "kein passendes Material hat (Verdacht auf Fake durch Tür auf/zu)?")
    nur_verdacht = st.checkbox("Nur Fake-Verdacht anzeigen", value=True)
    such = st.text_input("Filter — Kunde oder Seriennummer (optional)", "", key="vbm_q")
    clauses = ["validierung = 'verdacht_fake'"] if nur_verdacht else ["TRUE"]
    params = {}
    if such.strip():
        clauses.append("(customer_name ILIKE :q OR device_serial ILIKE :q)")
        params["q"] = f"%{such.strip()}%"
    df = frame(
        "SELECT customer_name, manufacturer_canonical, model_display, device_serial, colorant, marker_name, "
        "cartridge_serial, event_date, pages_since_previous, validierung "
        f"FROM insights.vw_vbm_validation WHERE {' AND '.join(clauses)} ORDER BY event_date DESC LIMIT 500",
        params,
    )
    if not df.empty:
        df["validierung"] = df["validierung"].map(VALID_LABEL).fillna(df["validierung"])
        df = df.rename(columns={
            "customer_name": "Kunde", "manufacturer_canonical": "Hersteller", "model_display": "Modell",
            "device_serial": "Geräte-Seriennummer", "colorant": "Farbe", "marker_name": "Material",
            "cartridge_serial": "Material-Seriennummer", "event_date": "Datum",
            "pages_since_previous": "Gelaufene Seiten", "validierung": "Validierung",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Teilewechsel (max. 500)")
    st.dataframe(df, width="stretch", hide_index=True)

with tab_einbau:
    st.markdown("**Material-Einbau-Prüfung** — wo wurde ein im Service-System gebuchter Toner laut "
                "Flotten-Verwaltung tatsächlich eingebaut?")
    st.caption("„Woanders eingebaut\" = auf einem anderen Gerät desselben Kunden → Hinweis auf Falschbuchung "
               "oder Lager-Umverteilung.")
    optionen = list(EINBAU_LABEL.keys())
    auswahl = st.multiselect(
        "Status", options=optionen, default=["woanders_eingebaut"], format_func=lambda v: EINBAU_LABEL.get(v, v)
    )
    df = frame(
        "SELECT booked_serial, colorant, lieferdatum, description, einbau_status "
        "FROM insights.vw_material_install_check WHERE einbau_status = ANY(:sel) "
        "ORDER BY lieferdatum DESC LIMIT 500",
        {"sel": auswahl or optionen},
    )
    if not df.empty:
        df["einbau_status"] = df["einbau_status"].map(EINBAU_LABEL).fillna(df["einbau_status"])
        df = df.rename(columns={
            "booked_serial": "Gebucht auf Seriennummer", "colorant": "Farbe", "lieferdatum": "Lieferdatum",
            "description": "Material", "einbau_status": "Einbau-Status",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Lieferung(en) (max. 500)")
    st.dataframe(df, width="stretch", hide_index=True)

with tab_kunde:
    st.markdown("**Kunden-Abgleich** — stimmt der Kunde/Standort eines Geräts in FleetMgmt und Radix überein?")
    st.caption("Abweichungen entstehen durch weiterverkaufte Geräte, Umzüge oder falsche Zuordnung — und sind "
               "eine häufige Ursache für Toner-Fehlversand und Falschabrechnung. Namen werden für den Vergleich "
               "normalisiert (Rechtsform, Schreibweise), damit nur echte Abweichungen übrig bleiben.")
    stufe = st.radio(
        "Stufe", options=list(ABGLEICH_LABEL.keys()), index=0, horizontal=True,
        format_func=lambda v: ABGLEICH_LABEL.get(v, v),
    )
    such = st.text_input("Filter — Kunde oder Seriennummer (optional)", "", key="kunde_q")
    clauses = ["abgleich = :st"]
    params = {"st": stufe}
    if such.strip():
        clauses.append("(fleet_kunde ILIKE :q OR radix_kunde ILIKE :q OR device_serial ILIKE :q)")
        params["q"] = f"%{such.strip()}%"
    df = frame(
        "SELECT device_serial, model_display, fleet_kunde, fleet_ort, radix_kunde, radix_ort, ort_gleich "
        f"FROM insights.vw_customer_device_mismatch WHERE {' AND '.join(clauses)} "
        "ORDER BY ort_gleich ASC, device_serial LIMIT 500",
        params,
    )
    if not df.empty:
        df["ort_gleich"] = df["ort_gleich"].map({True: "ja", False: "nein"})
        df = df.rename(columns={
            "device_serial": "Geräte-Seriennummer", "model_display": "Modell",
            "fleet_kunde": "Kunde (FleetMgmt)", "fleet_ort": "Ort (FleetMgmt)",
            "radix_kunde": "Kunde (Radix)", "radix_ort": "Ort (Radix)", "ort_gleich": "Ort gleich",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Gerät(e) (max. 500)")
    st.dataframe(df, width="stretch", hide_index=True)
