"""
Geld & Chancen — der Job-Einstieg „wo holen wir Geld / wo ist Markt-Signal".

Buendelt die kommerziell verwertbaren Signale, die vorher unter „Datenqualitaet"
versteckt waren: Lizenz-Verschwendung (CSP-Kostenleck) und das Wettbewerbs-Radar
(„Spionage"). Verweist auf die weiteren Geld-Quellen, die ihre eigene Methodik-Seite
haben (Garantie/Toner-Verschwendung, Ersatzteil-Fruehausfaelle, Up-Sell).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from insights.core.db import insights_engine
from insights.ui.links import doc
from insights.ui.theme import bar, render_chart, setup_page
from sqlalchemy import text


@st.cache_data(ttl=300)
def frame(sql: str, params: dict | None = None) -> pd.DataFrame:
    with insights_engine().connect() as conn:
        return pd.DataFrame(conn.execute(text(sql), params or {}).mappings().all())


@st.cache_data(ttl=300)
def kennzahlen() -> dict:
    with insights_engine().connect() as conn:
        lizenz_hoch = conn.execute(
            text("SELECT count(*) FROM insights.vw_lizenz_verschwendung WHERE lizenz_risiko = 'hoch'")
        ).scalar()
        konkurrenz_neu = conn.execute(
            text("SELECT count(*) FROM insights.vw_fremdgeraete WHERE konkurrenzmarke AND neu_aufgetaucht")
        ).scalar()
    return {"lizenz_hoch": lizenz_hoch, "konkurrenz_neu": konkurrenz_neu}


setup_page(
    "💰 Geld & Chancen",
    "Wo Geld zurueckzuholen ist und wo der Markt sich bewegt — Kostenlecks, "
    "Reklamations-Chancen und Wettbewerbs-Signale auf einen Blick.",
)
st.caption(f"📖 Methodik & Begruendung: [Doku Datenqualitaet]({doc('datenqualitaet.md')})")

k = kennzahlen()
c1, c2 = st.columns(2)
c1.metric("Lizenz-Verschwendung (hoch)", f"{k['lizenz_hoch']:,}".replace(",", "."),
          help="Geraete, die noch CSP-lizenziert sind, aber nie/lange nicht gemeldet haben und "
               "nicht in Radix sind — wahrscheinlich abgebaut. Kosten Lizenz ohne Nutzen.")
c2.metric("Konkurrenzgeraete (neu)", f"{k['konkurrenz_neu']:,}".replace(",", "."),
          help="Neue Fremdmarken-Geraete, die ueber unseren Agent melden, aber nicht von uns sind — "
               "der Kunde hat fremd beschafft (Wettbewerbs-Intel).")

st.info(
    "**Weitere Geld-Quellen** mit eigener Methodik-Seite: **Garantie-Reklamation** & "
    "**Toner-Verschwendung** (Seite Verbrauchsmaterial) · **Ersatzteil-Fruehausfaelle** "
    "(Seite Ersatzteile & Standzeit) · **Up-Sell / Geraete ohne Vertrag** (Seite Kosten & Vertraege)."
)

st.divider()
tab_lizenz, tab_spy = st.tabs(["💸 Lizenz-Verschwendung", "🕵️ Spionage / Fremdgeräte"])

with tab_lizenz:
    st.markdown("**Geräte, die noch CSP-lizenziert sind, aber nicht mehr aktiv sind** — "
                "Delisting-Kandidaten, die unnötig Lizenzgebühren kosten.")
    st.caption("CSP nimmt Geräte automatisch unter Lizenz, auch abgebaute/ersetzte. „lizenziert\" = in "
               "FleetMgmt gezählt (nicht gelöscht/deaktiviert), aber nicht mehr live. Stufe **hoch** = nie "
               "gemeldet oder >1 Jahr still UND nicht in Radix bzw. ohne Modell (fast sicher weg). "
               "Vor dem Delisting in CSP je Zeile den Grund prüfen. Einsparung = Anzahl x Lizenzgebühr/Gerät.")
    risiko_f = st.radio("Stufe", options=["hoch", "mittel", "niedrig"], index=0, horizontal=True,
                        format_func=lambda v: {"hoch": "Hoch (fast sicher weg)", "mittel": "Mittel (>180 Tage)",
                                               "niedrig": "Niedrig (60-180 Tage)"}.get(v, v))
    such_l = st.text_input("Filter — Kunde oder Seriennummer (optional)", "", key="lizenz_q")
    clauses_l = ["lizenz_risiko = :r"]
    params_l: dict = {"r": risiko_f}
    if such_l.strip():
        clauses_l.append("(customer_name ILIKE :q OR device_serial ILIKE :q)")
        params_l["q"] = f"%{such_l.strip()}%"
    df = frame(
        "SELECT customer_name, customer_city, manufacturer_canonical, model_display, device_serial, "
        "radix_device_number, device_status, letzte_meldung, tage_inaktiv, in_radix, aktiver_vertrag, grund "
        f"FROM insights.vw_lizenz_verschwendung WHERE {' AND '.join(clauses_l)} "
        "ORDER BY tage_inaktiv DESC NULLS FIRST LIMIT 500",
        params_l,
    )
    if not df.empty:
        df["in_radix"] = df["in_radix"].map({True: "ja", False: "nein"})
        df["aktiver_vertrag"] = df["aktiver_vertrag"].map({True: "ja", False: "nein"})
        df["device_status"] = df["device_status"].map(
            {"silent": "Still", "never_reported": "Nie gemeldet"}).fillna(df["device_status"])
        df = df.rename(columns={
            "customer_name": "Kunde", "customer_city": "Ort", "manufacturer_canonical": "Hersteller",
            "model_display": "Modell", "device_serial": "Geräte-Seriennummer", "radix_device_number": "Radix-ID",
            "device_status": "Status", "letzte_meldung": "Letzte Meldung", "tage_inaktiv": "Tage inaktiv",
            "in_radix": "In Radix", "aktiver_vertrag": "Aktiver Vertrag", "grund": "Grund",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Delisting-Kandidat(en) (max. 500)")
    st.dataframe(df, width="stretch", hide_index=True)

with tab_spy:
    st.markdown("**Geräte, die über unseren Flotten-Agent (DCA) melden, aber nicht von uns serviciert sind** — "
                "sichtbar, weil der Agent beim Kunden noch läuft.")
    st.caption("Bleibt der DCA nach Vertragsende auf dem Kundenserver, melden sich dort weiter alle Geräte "
               "automatisch — auch neue Konkurrenzgeräte, die der Kunde aufstellt. Signal: live (meldet jetzt) "
               "+ nicht in Radix (kein KR-Service). „Konkurrenzmarke\" = Marke ist nicht KM/Lexmark/HP/Kyocera. "
               "„Verlorener Kunde\" = beim Kunden keine KR-Geräte mehr → Win-Back oder Agent deinstallieren. "
               "Identitätslose Print-Server-Warteschlangen (IP „PS…\", ohne Modell/Serial) sind ausgefiltert.")
    cc1, cc2 = st.columns(2)
    nur_konk = cc1.checkbox("Nur Konkurrenz-Marken", value=True)
    nur_neu = cc2.checkbox("Nur neu aufgetaucht (< 1 Jahr)", value=False)
    such_s = st.text_input("Filter — Kunde (optional)", "", key="spy_q")
    clauses_s = ["TRUE"]
    params_s: dict = {}
    if nur_konk:
        clauses_s.append("konkurrenzmarke")
    if nur_neu:
        clauses_s.append("neu_aufgetaucht")
    if such_s.strip():
        clauses_s.append("customer_name ILIKE :q")
        params_s["q"] = f"%{such_s.strip()}%"
    df = frame(
        "SELECT customer_name, customer_city, manufacturer_canonical, model_display, device_serial, "
        "hostname, deployed_date, letzte_meldung, neu_aufgetaucht, konkurrenzmarke, "
        "kr_geraete_beim_kunden, einordnung "
        f"FROM insights.vw_fremdgeraete WHERE {' AND '.join(clauses_s)} "
        "ORDER BY konkurrenzmarke DESC, deployed_date DESC NULLS LAST LIMIT 500",
        params_s,
    )
    if not df.empty:
        for col in ("neu_aufgetaucht", "konkurrenzmarke"):
            df[col] = df[col].map({True: "ja", False: "nein"})
        df["einordnung"] = df["einordnung"].map({
            "verlorener_kunde_agent_aktiv": "Verlorener Kunde (Agent aktiv)",
            "fremdgeraet_bei_aktivem_kunden": "Fremdgerät bei aktivem Kunden"}).fillna(df["einordnung"])
        df = df.rename(columns={
            "customer_name": "Kunde", "customer_city": "Ort", "manufacturer_canonical": "Hersteller",
            "model_display": "Modell", "device_serial": "Geräte-Seriennummer", "hostname": "Hostname",
            "deployed_date": "Aufgetaucht", "letzte_meldung": "Letzte Meldung",
            "neu_aufgetaucht": "Neu (<1J)", "konkurrenzmarke": "Konkurrenzmarke",
            "kr_geraete_beim_kunden": "KR-Geräte beim Kunden", "einordnung": "Einordnung",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Fremdgerät(e) (max. 500)")
    st.dataframe(df, width="stretch", hide_index=True)
    # kleines Konkurrenzmarken-Balkenbild
    konk = frame("SELECT manufacturer_canonical AS marke, count(*) n FROM insights.vw_fremdgeraete "
                 "WHERE konkurrenzmarke GROUP BY 1 ORDER BY 2 DESC")
    if not konk.empty:
        render_chart(bar(konk, x="n", y="marke", top=12,
                         labels={"n": "Geräte", "marke": "Konkurrenzmarke"},
                         title="Fremdgeräte nach Konkurrenzmarke"))
