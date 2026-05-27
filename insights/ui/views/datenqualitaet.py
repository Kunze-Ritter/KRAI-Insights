"""
Datenqualität & Abgleich — Flotten-Verwaltung gegen Service-System (Radix)
gegenprüfen: Abrechnungs-Risiko (Schätz- statt Echt-Zähler), Flotten-Abgleich,
validierte Teilewechsel und die Frage, wo ein gebuchter Toner wirklich eingebaut wurde.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from insights.core.db import insights_engine
from insights.ui.links import doc
from insights.ui.theme import bar, render_chart, setup_page
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
IP_LABEL = {
    "fleet": "IP bestätigt FleetMgmt",
    "radix": "IP bestätigt Radix",
    "beide": "gemeinsames Subnetz (nicht eindeutig)",
    "unklar": "kein Subnetz-Treffer",
    "kein_ip": "keine IP",
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
        lizenz_hoch = conn.execute(
            text("SELECT count(*) FROM insights.vw_lizenz_verschwendung WHERE lizenz_risiko = 'hoch'")
        ).scalar()
        konkurrenz_neu = conn.execute(
            text("SELECT count(*) FROM insights.vw_fremdgeraete WHERE konkurrenzmarke AND neu_aufgetaucht")
        ).scalar()
    return {"risiko": risiko, "fake": fake, "woanders": woanders, "kunde_abw": kunde_abw,
            "lizenz_hoch": lizenz_hoch, "konkurrenz_neu": konkurrenz_neu}


setup_page(
    "🔍 Datenqualität & Abgleich",
    "Flotten-Verwaltung und Service-System gegeneinander prüfen — für saubere Abrechnung, "
    "korrekte Geräte-Zuordnung und weniger Toner-Fehlversand.",
)
st.caption(f"📖 Methodik & Begründung: [Doku Datenqualität & Abgleich]({doc('datenqualitaet.md')})")

k = kennzahlen()
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Lizenz-Verschwendung (hoch)", f"{k['lizenz_hoch']:,}".replace(",", "."),
          help="Geräte, die noch CSP-lizenziert sind, aber nie/lange nicht gemeldet haben und "
               "nicht in Radix sind — wahrscheinlich abgebaut. Kosten Lizenz ohne Nutzen.")
c2.metric("Konkurrenzgeräte (neu)", f"{k['konkurrenz_neu']:,}".replace(",", "."),
          help="Neue Fremdmarken-Geräte, die über unseren Agent melden, aber nicht von uns sind — "
               "der Kunde hat fremd beschafft (Wettbewerbs-Intel).")
c3.metric("Abrechnungs-Risiko (Geräte)", f"{k['risiko']:,}".replace(",", "."))
c4.metric("Teilewechsel mit Fake-Verdacht", f"{k['fake']:,}".replace(",", "."))
c5.metric("Toner woanders eingebaut", f"{k['woanders']:,}".replace(",", "."))
c6.metric("Kunden-Abweichung (Geräte)", f"{k['kunde_abw']:,}".replace(",", "."))

st.divider()
tab_lizenz, tab_spy, tab_ps, tab_risk, tab_recon, tab_vbm, tab_einbau, tab_kunde = st.tabs(
    ["💸 Lizenz-Verschwendung", "🕵️ Spionage / Fremdgeräte", "🖨️ Print-Server / Queues",
     "Abrechnungs-Risiko", "Flotten-Abgleich", "Teilewechsel-Validierung", "Material-Einbau", "Kunden-Abgleich"]
)

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

with tab_ps:
    st.markdown("**Kunden, die über einen zentralen Windows-Print-Server überwacht werden** — dort zählt der "
                "Agent (DCA) die Druck-Warteschlangen als identitätslose „Phantom-Geräte\" mit.")
    st.caption("Wird nicht jedes Gerät direkt, sondern ein zentraler Print-Server überwacht, liest der Agent "
               "dessen Druck-Queues mit. Queues ohne SNMP-Antwort landen als „Gerät\" mit dem Queue-Namen im "
               "IP-Feld (kein Serial/Modell/Hersteller/MAC) = Spooler-Artefakte. Diese sind seit Migration 061 "
               "als `is_queue_artifact` markiert und aus den Live- und Lizenz-Zahlen herausgerechnet (414 "
               "flotten-weit). „Echte Live-Geräte\" = real überwachte Geräte des Kunden. "
               "Nutzen: Service/Cleanup (Agent bei Vertragsende deinstallieren) und Erklärung, woher "
               "Phantom-Geräte stammen.")
    df = frame(
        "SELECT customer_name, customer_city, queue_artefakte, echte_live_geraete, namensschema, beispiel_queue "
        "FROM insights.vw_print_server_kunden ORDER BY queue_artefakte DESC"
    )
    if not df.empty:
        render_chart(bar(
            df, x="queue_artefakte", y="customer_name", top=15,
            labels={"queue_artefakte": "Queue-Artefakte (Phantome)", "customer_name": "Kunde"},
            title="Print-Server-Queue-Artefakte je Kunde",
        ))
        df = df.rename(columns={
            "customer_name": "Kunde", "customer_city": "Ort", "queue_artefakte": "Queue-Artefakte",
            "echte_live_geraete": "Echte Live-Geräte", "namensschema": "Namensschema",
            "beispiel_queue": "Beispiel-Queue",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Kunde(n) mit Print-Server-Überwachung")
    st.dataframe(df, width="stretch", hide_index=True)

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
        "radix_device_number, device_status, telemetry_stale_days, contract_end "
        f"FROM insights.vw_billing_risk WHERE {' AND '.join(clauses)} "
        "ORDER BY telemetry_stale_days DESC NULLS LAST LIMIT 500",
        params,
    )
    if not df.empty:
        df = df.rename(columns={
            "customer_name": "Kunde", "customer_city": "Ort", "manufacturer_canonical": "Hersteller",
            "model_display": "Modell", "device_serial": "Geräte-Seriennummer",
            "radix_device_number": "Radix-ID", "device_status": "Status",
            "telemetry_stale_days": "Tage ohne Meldung", "contract_end": "Vertrag bis",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Gerät(e) (max. 500)")
    st.dataframe(df, width="stretch", hide_index=True)

with tab_recon:
    st.markdown("**Flotten-Abgleich** — Meldestatus, Vertrag und Vorhandensein im Service-System je Gerät.")
    st.caption("Eine Wahrheit pro Gerät: Ist es aktiv? Steht es unter Vertrag? Ist es in Radix bekannt?")
    _agg = frame("SELECT einordnung, count(*) AS n FROM insights.vw_fleet_reconciliation GROUP BY einordnung")
    if not _agg.empty:
        _agg["label"] = _agg["einordnung"].map(EINORDNUNG_LABEL).fillna(_agg["einordnung"])
        render_chart(bar(
            _agg, x="n", y="label",
            labels={"n": "Geräte", "label": "Einordnung"},
            title="Gesamte Flotte nach Einordnung",
        ))
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
        "radix_device_number, device_status, contract_active, contract_end, in_radix, einordnung "
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
            "model_display": "Modell", "device_serial": "Geräte-Seriennummer",
            "radix_device_number": "Radix-ID", "device_status": "Status",
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
        "SELECT customer_name, manufacturer_canonical, model_display, device_serial, radix_device_number, "
        "colorant, marker_name, cartridge_serial, event_date, pages_since_previous, validierung "
        f"FROM insights.vw_vbm_validation WHERE {' AND '.join(clauses)} ORDER BY event_date DESC LIMIT 500",
        params,
    )
    if not df.empty:
        df["validierung"] = df["validierung"].map(VALID_LABEL).fillna(df["validierung"])
        df = df.rename(columns={
            "customer_name": "Kunde", "manufacturer_canonical": "Hersteller", "model_display": "Modell",
            "device_serial": "Geräte-Seriennummer", "radix_device_number": "Radix-ID",
            "colorant": "Farbe", "marker_name": "Material",
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
        "SELECT booked_serial, radix_device_number, colorant, lieferdatum, description, einbau_status "
        "FROM insights.vw_material_install_check WHERE einbau_status = ANY(:sel) "
        "ORDER BY lieferdatum DESC LIMIT 500",
        {"sel": auswahl or optionen},
    )
    if not df.empty:
        df["einbau_status"] = df["einbau_status"].map(EINBAU_LABEL).fillna(df["einbau_status"])
        df = df.rename(columns={
            "booked_serial": "Gebucht auf Seriennummer", "radix_device_number": "Radix-ID",
            "colorant": "Farbe", "lieferdatum": "Lieferdatum",
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
    st.caption("Tipp: Bei „Abweichung\" zeigt die Spalte **IP-Beleg**, welches System die aktuelle "
               "Geräte-IP stützt — ein Gerät im Subnetz eines Kunden steht physisch dort. "
               "„IP bestätigt …\" ist eindeutig; das andere System sollte korrigiert werden.")
    such = st.text_input("Filter — Kunde oder Seriennummer (optional)", "", key="kunde_q")
    clauses = ["abgleich = :st"]
    params = {"st": stufe}
    if such.strip():
        clauses.append("(fleet_kunde ILIKE :q OR radix_kunde ILIKE :q OR device_serial ILIKE :q)")
        params["q"] = f"%{such.strip()}%"
    df = frame(
        "SELECT device_serial, radix_device_number, model_display, fleet_kunde, fleet_ort, radix_kunde, radix_ort, "
        "device_status, last_report, printer_ip, ip_subnetz, subnetz_passt_zu, ort_gleich "
        f"FROM insights.vw_customer_device_mismatch WHERE {' AND '.join(clauses)} "
        "ORDER BY (subnetz_passt_zu IN ('fleet','radix')) DESC, (device_status='live') DESC, device_serial LIMIT 500",
        params,
    )
    if not df.empty:
        df["ort_gleich"] = df["ort_gleich"].map({True: "ja", False: "nein"})
        df["device_status"] = df["device_status"].map(
            {"live": "Aktiv", "silent": "Still", "never_reported": "Nie gemeldet"}
        ).fillna(df["device_status"])
        df["subnetz_passt_zu"] = df["subnetz_passt_zu"].map(IP_LABEL).fillna(df["subnetz_passt_zu"])
        df = df.rename(columns={
            "device_serial": "Geräte-Seriennummer", "radix_device_number": "Radix-ID", "model_display": "Modell",
            "fleet_kunde": "Kunde (FleetMgmt)", "fleet_ort": "Ort (FleetMgmt)",
            "radix_kunde": "Kunde (Radix)", "radix_ort": "Ort (Radix)",
            "device_status": "Status", "last_report": "Letzte Meldung", "printer_ip": "IP-Adresse",
            "ip_subnetz": "Subnetz", "subnetz_passt_zu": "IP-Beleg", "ort_gleich": "Ort gleich",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Gerät(e) (max. 500)")
    st.dataframe(df, width="stretch", hide_index=True)
