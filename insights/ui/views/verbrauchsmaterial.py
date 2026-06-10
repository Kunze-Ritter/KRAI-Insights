"""
Verbrauchsmaterial — echte Standzeiten von Toner und Teilen, Vergleich zur
Hersteller-Angabe und Garantie-Bewertung.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from insights.core.db import insights_engine
from insights.ui.links import doc
from insights.ui.theme import NEG, POS, TONER, bar, line, render_chart, setup_page
from sqlalchemy import text

WARRANTY_LABEL = {
    "claim": "Garantiefall",
    "negotiation": "Verhandlungs-Kandidat",
    "vorzeitiger_tausch": "Vorzeitiger Tausch (Verschwendung)",
    "wear": "Verschleiß (normal)",
    "normal": "Normal",
    "artifact": "Messartefakt",
    "fehlmeldung": "Fehlmeldung (Wiedereinsetzen)",
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
        waste_eur = conn.execute(
            text("SELECT COALESCE(sum(verschwendung_eur), 0) FROM insights.vw_toner_waste")
        ).scalar()
        cov = conn.execute(text(
            "SELECT count(*) FILTER (WHERE hat_oem_daten), count(*) "
            "FROM insights.vw_device_oem_coverage WHERE device_status='live'"
        )).one()
    cov_pct = round(100.0 * cov[0] / cov[1]) if cov and cov[1] else 0
    return {"cls": cls, "flott": flott, "garantie": garantie, "waste_eur": waste_eur, "cov_pct": cov_pct}


@st.cache_data(ttl=300)
def frame(sql: str, params: dict | None = None) -> pd.DataFrame:
    with insights_engine().connect() as conn:
        return pd.DataFrame(conn.execute(text(sql), params or {}).mappings().all())


setup_page(
    "🧪 Verbrauchsmaterial — Standzeiten & Garantie",
    "Verbrauchsmaterial (Toner, Trommeln, Wartungsteile): wie lange ein Teil tatsächlich "
    "gehalten hat, im Vergleich zur Hersteller-Angabe — als Grundlage für Kalkulation und Garantie.",
)
st.caption(f"📖 Garantie-Logik, Fehlmeldungs-Filter & Restwert-Modell: [Doku Garantie]({doc('garantie.md')})")

with st.expander("📌 Woher kommen diese Daten? Was bedeuten die Begriffe?"):
    st.markdown(
        "**Datenquelle:** FleetMgmt meldet automatisch jeden Toner- oder Teilewechsel mit dem "
        "aktuellen Seitenzähler des Geräts. So weiß das System, wie viele Seiten ein Toner "
        "tatsächlich geliefert hat.  \n"
        "**Das Hersteller-Soll (OEM-Reichweite)** ist die vom Hersteller garantierte Seitenzahl "
        "(z. B. 'Toner für 8.000 Seiten bei 5 % Druckdeckung'). Diese Werte kommen aus unserem "
        "Lexmark/HP/Kyocera-Crawler oder direkt aus dem Service-System Radix.  \n\n"
        "**Wichtige Begriffe:**\n"
        "- *Standzeit* = Wie viele Seiten oder Tage ein Toner/Teil tatsächlich gehalten hat\n"
        "- *Garantiefall* = Toner innerhalb von 1 Jahr UND unter 70 % der Hersteller-Seitenzahl → "
        "Reklamation beim Hersteller möglich (Hersteller erstattet den ungenutzten Anteil)\n"
        "- *Vorzeitiger Tausch* = Toner wurde mit hoher Restfüllung weggeworfen — kein Defekt, "
        "aber bares Geld verschwendet (Beratungsmöglichkeit beim Kunden)\n"
        "- *OEM-Konfidenz* = Wie zuverlässig die Hersteller-Soll-Angabe ist: **hoch** = direkt "
        "aus Radix oder eindeutige Toner-SKU; **mittel/niedrig** = geschätzter Median, weil das "
        "Modell viele Toner-Varianten (Starter/Standard/XL) mit unterschiedlichen Reichweiten hat\n"
        "- *Deckungskorrektur* = Bei mehr als 5 % Druckdeckung verbraucht der Drucker mehr Toner "
        "pro Seite → die erreichbaren Seiten sinken. Das wird herausgerechnet, damit der "
        "Vergleich fair ist\n\n"
        "**Was sollte ich tun?**  \n"
        "→ Tab **Garantie-Bewertung**: Liste der Garantiefälle exportieren, Hersteller kontaktieren.  \n"
        "→ Tab **Toner-Verschwendung**: Kunden mit hohem Wegwerf-Wert ansprechen "
        "(Schulung oder Vertragsanpassung).  \n"
        "→ Tab **Resttonerbehälter**: Proaktive Lieferliste für die nächsten Wochen."
    )

k = kennzahlen()
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("OEM-Abdeckung (Live)", f"{k['cov_pct']} %",
          help="Anteil der Live-Geräte mit OEM-Reichweiten (Crawler: Lexmark/HP/Kyocera + "
               "KM-Liste). Basis für Garantie-/Standzeit-Bewertung.")
c2.metric("Echte Wechsel (mit Seriennummer)", f"{k['cls'].get('real_new_cartridge', 0):,}".replace(",", "."))
c3.metric("Standzeit vs. Hersteller-Soll", f"{int(k['flott'])} %" if k["flott"] else "—")
c4.metric("Mögliche Garantiefälle", f"{k['garantie'].get('claim', 0):,}".replace(",", "."),
          help="Nur (nahezu) leere Kartuschen unter 70 % Soll-Tonermenge — echte Frühausfälle.")
c5.metric("Vorzeitige Tausche", f"{k['garantie'].get('vorzeitiger_tausch', 0):,}".replace(",", "."),
          help="Kartuschen mit hoher Restfüllung weggeworfen — kein Defekt, sondern Verschwendung.")
c6.metric("Weggeworfener Toner", f"~{int(k['waste_eur'] or 0):,} €".replace(",", "."),
          help="Geschätzter Wert des weggeworfenen Toners (Restfüllung x Tonerpreis).")

st.divider()
tab_yield, tab_garantie, tab_waste, tab_box, tab_geraet = st.tabs(
    ["Standzeit vs. Hersteller-Soll", "Garantie-Bewertung", "💸 Toner-Verschwendung",
     "🗑️ Resttonerbehälter", "Verlauf je Gerät"]
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
        cd = df[["model_display", "avg_pct_of_oem"]].copy()
        cd["avg_pct_of_oem"] = pd.to_numeric(cd["avg_pct_of_oem"], errors="coerce")
        cd["Bewertung"] = (cd["avg_pct_of_oem"] >= 100).map({True: "≥ Soll", False: "< Soll"})
        render_chart(bar(
            cd, x="avg_pct_of_oem", y="model_display", color="Bewertung",
            color_map={"≥ Soll": POS, "< Soll": NEG}, ref=100, ref_label="Soll 100 %", top=20,
            labels={"avg_pct_of_oem": "Ø % vom Soll", "model_display": "Modell"},
            title="Toner-Standzeit vs. Soll (Top 20 Modelle)",
        ))
        df = df.rename(columns={
            "manufacturer_canonical": "Hersteller", "model_display": "Modell", "refills": "Wechsel",
            "devices": "Geräte", "avg_real_pages": "Ø echte Seiten",
            "oem_target_pages": "Hersteller-Soll (Seiten)", "avg_pct_of_oem": "Ø % vom Soll",
        })
    st.dataframe(df, width="stretch", hide_index=True)

with tab_garantie:
    st.markdown("**Garantie-Bewertung je Material-Lebenszyklus (Zeit und gelieferte Tonermenge).**")
    st.caption(
        "Garantiefall = innerhalb 1 Jahr UND unter 70 % der Soll-TONERMENGE. Wichtig: das Hersteller-Soll "
        "gilt bei 5 % Deckung — wer mit mehr Deckung druckt, bekommt weniger Seiten bei gleicher Tonermenge. "
        "Deshalb wird deckungskorrigiert gerechnet (Spalte % vom Soll Toner); die Spalte % vom Soll Seiten ist "
        "der unkorrigierte Rohwert. Deckung belegt = ja heißt: mit realer Deckung gerechnet (stärkster Nachweis)."
    )
    st.caption(
        "**OEM-Konfidenz**: hoch = Hersteller-Soll aus Radix belegt oder eindeutige Toner-SKU "
        "(zuverlässig); mittel/niedrig = Soll aus dem Modell-Median, wo das Modell viele Toner-Varianten "
        "(Starter/Standard/XL) mit großer Reichweiten-Spanne hat → Referenz unsicher. Headline-Zahlen "
        "zählen nur hoch+mittel. (Migration 062: Soll für ~85 % der Tonerwechsel verfügbar statt 14 %.)"
    )
    bewertung = st.multiselect(
        "Bewertung", options=["claim", "negotiation"], default=["claim", "negotiation"],
        format_func=lambda w: WARRANTY_LABEL.get(w, w),
    )
    konf = st.multiselect(
        "OEM-Konfidenz", options=["hoch", "mittel", "niedrig"], default=["hoch", "mittel"],
        format_func=lambda v: {"hoch": "Hoch (belastbar)", "mittel": "Mittel",
                               "niedrig": "Niedrig (unsichere Referenz)"}.get(v, v),
    )
    nur_serial = st.checkbox("Nur serial-belegte (stärkster Nachweis)", value=False,
                             help="Konica Minolta/Kyocera melden keine Seriennummer — diese Fälle sind "
                                  "über die Zähler belegt, aber ohne Serial.")
    such = st.text_input("Filter — Kunde, Hersteller oder Modell (optional)", "")
    clauses = ["warranty_class = ANY(:cls)"] if bewertung else ["TRUE"]
    params: dict = {}
    if bewertung:
        params["cls"] = bewertung
    if konf:
        clauses.append("oem_konfidenz = ANY(:konf)")
        params["konf"] = konf
    if nur_serial:
        clauses.append("cartridge_serial IS NOT NULL")
    if such.strip():
        clauses.append("(customer_name ILIKE :q OR manufacturer_canonical ILIKE :q OR model_display ILIKE :q)")
        params["q"] = f"%{such.strip()}%"
    df = frame(
        "SELECT customer_name, manufacturer_canonical, model_display, device_serial, radix_device_number, "
        "CASE WHEN colorant IS NOT NULL AND colorant <> '' THEN 'Toner' ELSE 'Teil (kein Toner)' END AS art, "
        "lower(NULLIF(colorant, '')) AS colorant, marker_name, "
        "cartridge_serial, installed_on, removed_on, age_days, pages, rated, "
        "pct_seiten_roh, coverage_real_pct, pct_of_oem, coverage_belegt, warranty_class, "
        "oem_konfidenz, oem_target_source "
        f"FROM insights.vw_warranty_assessment WHERE {' AND '.join(clauses)} "
        "ORDER BY (oem_konfidenz='hoch') DESC, (cartridge_serial IS NOT NULL) DESC, pct_of_oem ASC LIMIT 500",
        params,
    )
    if not df.empty:
        df["warranty_class"] = df["warranty_class"].map(WARRANTY_LABEL).fillna(df["warranty_class"])
        df["coverage_belegt"] = df["coverage_belegt"].map({True: "ja", False: "nein"})
        df = df.rename(columns={
            "customer_name": "Kunde", "manufacturer_canonical": "Hersteller", "model_display": "Modell",
            "device_serial": "Geräte-Seriennummer", "radix_device_number": "Radix-ID",
            "art": "Art", "colorant": "Farbe", "marker_name": "Material/Teil",
            "cartridge_serial": "Material-Seriennummer", "installed_on": "Eingebaut", "removed_on": "Gewechselt",
            "age_days": "Standzeit (Tage)", "pages": "Gelaufene Seiten", "rated": "Hersteller-Soll",
            "pct_seiten_roh": "% vom Soll (Seiten)", "coverage_real_pct": "reale Deckung %",
            "pct_of_oem": "% vom Soll (Toner, deckungskorr.)", "coverage_belegt": "Deckung belegt",
            "warranty_class": "Bewertung",
            "oem_konfidenz": "OEM-Konfidenz",
            "oem_target_source": "Soll-Quelle",
        })
        df["Soll-Quelle"] = df["Soll-Quelle"].map(
            {"fleetmgmt": "Radix", "modell_median": "Modell-Median"}).fillna(df["Soll-Quelle"])
    st.write(f"**{len(df):,}**".replace(",", ".") + " Eintrag/Einträge (max. 500)")
    st.dataframe(df, width="stretch", hide_index=True)

with tab_waste:
    st.markdown("**Toner-Verschwendung: Kartuschen, die mit hoher Restfüllung weggeworfen wurden.**")
    st.caption(
        "Kein Garantiefall, sondern eine eigene Geld-Quelle: hier wirft der Kunde nutzbaren Toner weg "
        "(Kartusche > 20 % voll getauscht). Geschätzter Wert = Restfüllung x Tonerpreis je Hersteller. "
        "Aktionsliste fürs Vertrags-/Beratungsgespräch."
    )
    such_w = st.text_input("Filter — Kunde (optional)", "", key="waste_filter")
    clauses_w = ["TRUE"]
    params_w: dict = {}
    if such_w.strip():
        clauses_w.append("customer_name ILIKE :q")
        params_w["q"] = f"%{such_w.strip()}%"
    df = frame(
        "SELECT customer_name, customer_city, manufacturer_canonical, vorzeitige_tausche, geraete, "
        "avg_restfuellung_pct, verschwendung_eur "
        f"FROM insights.vw_toner_waste WHERE {' AND '.join(clauses_w)} "
        "ORDER BY verschwendung_eur DESC LIMIT 200",
        params_w,
    )
    if not df.empty:
        total = int(pd.to_numeric(df["verschwendung_eur"], errors="coerce").sum())
        tausche = int(pd.to_numeric(df["vorzeitige_tausche"], errors="coerce").sum())
        m1, m2 = st.columns(2)
        m1.metric("Weggeworfener Toner (gefiltert)", f"~{total:,} €".replace(",", "."))
        m2.metric("Vorzeitige Tausche", f"{tausche:,}".replace(",", "."))
        cd = df[["customer_name", "verschwendung_eur"]].copy()
        cd["verschwendung_eur"] = pd.to_numeric(cd["verschwendung_eur"], errors="coerce")
        render_chart(bar(
            cd, x="verschwendung_eur", y="customer_name", single_color=NEG, top=15,
            labels={"verschwendung_eur": "Weggeworfener Toner (€)", "customer_name": "Kunde"},
            title="Top-Kunden nach weggeworfenem Toner (€)",
        ))
        df = df.rename(columns={
            "customer_name": "Kunde", "customer_city": "Ort", "manufacturer_canonical": "Hersteller",
            "vorzeitige_tausche": "Vorzeitige Tausche", "geraete": "Geräte",
            "avg_restfuellung_pct": "Ø Restfüllung %", "verschwendung_eur": "Weggeworfen (€)",
        })
    st.dataframe(df, width="stretch", hide_index=True)

with tab_box:
    st.markdown("**Resttonerbehälter-Vorhersage über den Seitenzähler (proaktive Lieferung).**")
    st.caption(
        "Viele Geräte messen den Resttonerbehälter schlecht (52 % der Sensor-Events sind Rauschen). "
        "Deshalb prognostizieren wir über den zuverlässigen Seitenzähler: Seiten seit letztem echten "
        "Wechsel vs. Box-Reichweite je Modell (KM realisiert / Lexmark OEM-Soll / Flotten-Median). "
        "Nur Geräte mit verlässlichem Anker bekommen eine Punkt-Prognose; bei unzuverlässigem Sensor "
        "(Lexmark XC/CX, HP E87xx, Kyocera-Color) bitte feste Kadenz nach der Box-Reichweite planen."
    )
    dring = st.multiselect("Dringlichkeit", options=["faellig", "bald", "ok"], default=["faellig", "bald"],
                           format_func=lambda d: {"faellig": "Fällig (≥80 %)", "bald": "Bald (60-80 %)",
                                                  "ok": "OK (<60 %)"}.get(d, d))
    such_b = st.text_input("Filter — Kunde (optional)", "", key="box_filter")
    clauses_b = ["mess_qualitaet = 'verlässlich'"]
    params_b: dict = {}
    if dring:
        clauses_b.append("dringlichkeit = ANY(:dr)")
        params_b["dr"] = dring
    if such_b.strip():
        clauses_b.append("customer_name ILIKE :q")
        params_b["q"] = f"%{such_b.strip()}%"
    df = frame(
        "SELECT customer_name, customer_city, manufacturer_canonical, model_display, device_serial, "
        "radix_device_number, pct_voll, tage_bis_voll, seiten_seit_wechsel, referenz_seiten, referenz_basis, "
        "dringlichkeit FROM insights.vw_waste_box_forecast "
        f"WHERE {' AND '.join(clauses_b)} ORDER BY pct_voll DESC NULLS LAST LIMIT 300",
        params_b,
    )
    faellig_n = int((df["dringlichkeit"] == "faellig").sum()) if not df.empty else 0
    m1, m2 = st.columns(2)
    m1.metric("Fällig (≥80 % voll)", f"{faellig_n}")
    m2.metric("Liste (gefiltert)", f"{len(df)}")
    if not df.empty:
        df["dringlichkeit"] = df["dringlichkeit"].map(
            {"faellig": "Fällig", "bald": "Bald", "ok": "OK"}).fillna(df["dringlichkeit"])
        df = df.rename(columns={
            "customer_name": "Kunde", "customer_city": "Ort", "manufacturer_canonical": "Hersteller",
            "model_display": "Modell", "device_serial": "Geräte-Seriennummer", "radix_device_number": "Radix-ID",
            "pct_voll": "% voll (geschätzt)", "tage_bis_voll": "Tage bis voll",
            "seiten_seit_wechsel": "Seiten seit Wechsel", "referenz_seiten": "Box-Reichweite (Seiten)",
            "referenz_basis": "Referenz-Basis", "dringlichkeit": "Dringlichkeit",
        })
    st.dataframe(df, width="stretch", hide_index=True)
    st.caption(
        "Hinweis: Tage bis voll negativ = bereits überfällig (sofort liefern). Geräte mit unzuverlässigem "
        "Sensor sind hier ausgeblendet — ihre Box-Reichweite je Modell steht in der Standzeit-Doku."
    )

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
            cd = df.copy()
            cd["colorant"] = cd["colorant"].replace("", "Teil")
            cd = cd.dropna(subset=["pct_of_oem"])
            if not cd.empty:
                render_chart(line(
                    cd, x="datum", y="pct_of_oem", color="colorant", color_map=TONER,
                    ref=100, ref_label="Soll 100 %",
                    labels={"datum": "Datum", "pct_of_oem": "% vom Soll", "colorant": "Farbe"},
                    title="Standzeit-Verlauf je Material (% vom Soll)",
                ))
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
