"""
Ersatzteile & Standzeit — Frühausfälle (Reklamation/Geld zurück) und reale
Standzeit je Modell/Teiltyp (Vorhersage/PM). Gilt für alle Teile, nicht nur Toner.
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
        fa = conn.execute(text("SELECT count(*) FROM insights.vw_part_early_failures")).scalar()
        geraete = conn.execute(
            text("SELECT count(DISTINCT device_serial) FROM insights.vw_part_early_failures")
        ).scalar()
        modelle = conn.execute(text("SELECT count(*) FROM insights.vw_part_lifetime_stats")).scalar()
    return {"fa": fa, "geraete": geraete, "modelle": modelle}


setup_page(
    "🔧 Ersatzteile & Standzeit",
    "Ersatzteile (Fixiereinheit, Trommel, Walzen, Boards …) — wo wir zu früh tauschen "
    "(Reklamation/Geld zurück) und wie lange ein Teil je Modell real hält (Vorhersage/PM).",
)
st.caption("📖 Methodik (Standzeit aus Wiedereinbau, Tage + Seiten): "
           f"[Doku Garantie]({doc('garantie.md', '6-ersatzteile-nicht-nur-toner')})")

with st.expander("📌 Woher kommen diese Daten? Was bedeuten 'Frühausfälle'?"):
    st.markdown(
        "**Datenquelle:** Service-System Radix — Techniker erfassen nach jedem Einsatz, "
        "welche Ersatzteile eingebaut wurden. Das System vergleicht das Einbaudatum des "
        "neuen Teils mit dem vorherigen Einbau desselben Teils am gleichen Gerät.  \n\n"
        "**Was ist ein 'Frühausfall'?**  \n"
        "Wenn ein Ersatzteil innerhalb von ca. einem Jahr **erneut** getauscht werden muss, "
        "gilt das als Frühausfall. Mögliche Ursachen:\n"
        "- Das Teil war defekt (Herstellerfehler → Reklamation beim Hersteller)\n"
        "- Das Teil wurde bei der Reparatur beschädigt eingebaut\n"
        "- Ein anderes, nicht erkanntes Problem hat das Teil erneut zerstört  \n\n"
        "**Frühausfälle bedeuten Geld zurück:** Die meisten Ersatzteile haben eine Hersteller-"
        "Garantie. Bei Frühausfällen kann KR das Teil und ggf. die Arbeitszeit beim Hersteller "
        "reklamieren — besonders bei serial-belegten Teilen (starker Nachweis).  \n\n"
        "**Tab Standzeit je Modell/Teil:** Zeigt, wie lange ein bestimmtes Teil an einem "
        "bestimmten Modell im Schnitt hält. Basis für die vorausschauende Wartungsplanung (PM): "
        "Teile proaktiv tauschen, bevor sie ausfallen und einen Servicebesuch erzwingen.  \n\n"
        "**Was sollte ich tun?**  \n"
        "→ Tab **Frühausfälle**: Reklamationen beim Hersteller einleiten — Radix-ID + "
        "Einbaudatum als Nachweis verwenden.  \n"
        "→ Tab **Standzeit je Modell**: Teile mit kurzer Standzeit in PM-Pläne aufnehmen."
    )

k = kennzahlen()
c1, c2, c3 = st.columns(3)
c1.metric("Frühausfälle (≤ 1 Jahr)", f"{k['fa']:,}".replace(",", "."))
c2.metric("betroffene Geräte", f"{k['geraete']:,}".replace(",", "."))
c3.metric("Modell/Teil-Standzeiten", f"{k['modelle']:,}".replace(",", "."))

st.divider()
tab_fa, tab_lz = st.tabs(["Frühausfälle (Reklamation)", "Standzeit je Modell/Teil (PM)"])

with tab_fa:
    st.markdown("**Ersatzteile, die innerhalb der ~1-Jahres-Garantie erneut getauscht wurden** — "
                "Frühausfall → Reklamation/Geld-zurück prüfen. Mit Symptom/Diagnose aus dem Ticket.")
    teiltyp = st.text_input("Teiltyp filtern (z. B. Fixier, Trommel, Walze)", "", key="fa_typ")
    such = st.text_input("Filter — Kunde (optional)", "", key="fa_q")
    clauses = ["TRUE"]
    params: dict = {}
    if teiltyp.strip():
        clauses.append("teiltyp ILIKE :t")
        params["t"] = f"%{teiltyp.strip()}%"
    if such.strip():
        clauses.append("customer_name ILIKE :q")
        params["q"] = f"%{such.strip()}%"
    df = frame(
        "SELECT customer_name, manufacturer_canonical, model_display, device_serial, radix_device_number, "
        "teiltyp, description, basis, standzeit_tage, standzeit_seiten, oem_nominal_seiten, pct_vom_oem, "
        "einbau_datum, erneut_getauscht, diagnose "
        f"FROM insights.vw_part_early_failures WHERE {' AND '.join(clauses)} "
        "ORDER BY pct_vom_oem ASC NULLS LAST, standzeit_tage ASC LIMIT 500",
        params,
    )
    if not df.empty:
        df = df.rename(columns={
            "customer_name": "Kunde", "manufacturer_canonical": "Hersteller", "model_display": "Modell",
            "device_serial": "Geräte-Seriennummer", "radix_device_number": "Radix-ID",
            "teiltyp": "Teiltyp", "description": "Teil",
            "basis": "Bewertung", "standzeit_tage": "Standzeit (Tage)", "standzeit_seiten": "Standzeit (Seiten)",
            "oem_nominal_seiten": "Hersteller-Soll (Seiten)", "pct_vom_oem": "% vom Soll",
            "einbau_datum": "Eingebaut", "erneut_getauscht": "Erneut getauscht", "diagnose": "Diagnose/Symptom",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Frühausfall/Frühausfälle (max. 500)")
    st.dataframe(df, width="stretch", hide_index=True)

with tab_lz:
    st.markdown("**Reale Standzeit je Modell und Teiltyp** (Median aus Wiedereinbau-Intervallen, "
                "ab 5 Wechseln) — in Tagen und, wo Zählerdaten vorliegen, in Seiten.")
    st.caption("Niedrige Standzeit = störanfälliges Teil/Modell. Basis für Vorhersage (PM) und "
               "Erkennung von zu frühem Tausch.")
    teiltyp = st.text_input("Teiltyp filtern", "", key="lz_typ")
    modell = st.text_input("Modell filtern", "", key="lz_mod")
    clauses = ["TRUE"]
    params = {}
    if teiltyp.strip():
        clauses.append("teiltyp ILIKE :t")
        params["t"] = f"%{teiltyp.strip()}%"
    if modell.strip():
        clauses.append("modell ILIKE :m")
        params["m"] = f"%{modell.strip()}%"
    df = frame(
        "SELECT hersteller, modell, teiltyp, stichproben, geraete, median_standzeit_tage, "
        "stichproben_seiten, median_standzeit_seiten, oem_nominal_seiten "
        f"FROM insights.vw_part_lifetime_stats WHERE {' AND '.join(clauses)} "
        "ORDER BY median_standzeit_tage ASC LIMIT 500",
        params,
    )
    if not df.empty:
        cd = df.dropna(subset=["median_standzeit_tage"]).copy()
        if not cd.empty:
            cd["teil"] = cd["modell"].astype(str) + " · " + cd["teiltyp"].astype(str)
            render_chart(bar(
                cd, x="median_standzeit_tage", y="teil", order="asc", top=20,
                labels={"median_standzeit_tage": "Median Standzeit (Tage)", "teil": "Modell · Teil"},
                hover_data=["hersteller", "stichproben", "geraete"],
                title="Kürzeste Standzeiten — störanfälligste Teile (Top 20)",
            ))
        df = df.rename(columns={
            "hersteller": "Hersteller", "modell": "Modell", "teiltyp": "Teiltyp",
            "stichproben": "Wechsel (Stichproben)", "geraete": "Geräte",
            "median_standzeit_tage": "Median Standzeit (Tage)",
            "stichproben_seiten": "davon mit Seitenwert", "median_standzeit_seiten": "Median Standzeit (Seiten)",
            "oem_nominal_seiten": "Hersteller-Soll (Seiten)",
        })
    st.write(f"**{len(df):,}**".replace(",", ".") + " Modell/Teiltyp-Kombination(en)")
    st.dataframe(df, width="stretch", hide_index=True)
