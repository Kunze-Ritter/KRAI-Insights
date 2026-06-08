"""
Service — Teile-Einsatz & Schulung („Shotgun-Reparatur" aufdecken).

Findet Muster, wo bei einem Einsatz auf Verdacht viele Teile (Trommel, Entwickler,
Transfer, Fixierer …) auf einmal getauscht werden, statt gezielt — um Techniker zu
schulen. Geplante Wartung/Installation (Teile-Kit korrekt) ist bewusst ausgenommen.
Start-Fokus: Symptom → Teil-Muster. Quelle: vw_service_visits & Co. (Migration 066).
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


def _de(n: float | int) -> str:
    return f"{round(n):,}".replace(",", ".")


setup_page(
    "🧰 Service — Teile-Einsatz & Schulung",
    "Wo werden bei einem Einsatz auf Verdacht zu viele Teile getauscht? Muster finden, "
    "um Techniker zu schulen. Geplante Wartung/Installation ist ausgenommen.",
)
st.caption(f"📖 Methodik & Definitionen: [Doku Service]({doc('service.md')})")

# --- KPIs (nur Störungs-/Reparatur-Einsätze, Wartung getrennt) -------------
kpi = frame(
    "SELECT count(*) AS einsaetze, "
    "count(*) FILTER (WHERE shotgun_verdacht) AS shotgun, "
    "round(avg(teiltypen), 2) AS schnitt, "
    "round(sum(material_eur) FILTER (WHERE shotgun_verdacht)) AS shotgun_eur "
    "FROM insights.vw_service_visits WHERE symptom <> 'Wartung/Installation'"
)
if not kpi.empty:
    r = kpi.iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reparatur-Einsätze (mit Teilen)", _de(r["einsaetze"] or 0))
    c2.metric("Shotgun-Verdacht (≥3 Teiltypen)", _de(r["shotgun"] or 0),
              help="Einsätze mit 3+ verschiedenen Teiltypen, die KEINE geplante Wartung sind.")
    c3.metric("Ø Teiltypen je Einsatz", f"{r['schnitt'] or 0}")
    c4.metric("Material-€ auf Verdachts-Einsätzen", _de(r["shotgun_eur"] or 0) + " €",
              help="Material auf den Verdachts-Einsätzen — Hinweis auf mögliche Über-Tausche, "
                   "kein bewiesener Verlust.")

st.divider()
tab_sym, tab_shot, tab_tech = st.tabs(
    ["🎯 Symptom → Teil-Muster", "🧰 Shotgun-Einsätze", "👷 Techniker-Profil"]
)

# --- Tab 1: Symptom -> Teil-Muster (START-Fokus) ----------------------------
with tab_sym:
    st.markdown("**Bei welcher Fehlermeldung/Symptom werden wie viele (und welche) Teile getauscht?** "
                "Hohe Ø-Teiltypen oder Shotgun-Quote = hier lohnt die Schulung.")
    pat = frame(
        "SELECT symptom, einsaetze, schnitt_teiltypen, shotgun_einsaetze, shotgun_pct, "
        "material_eur, haeufigste_teilkombi FROM insights.vw_symptom_part_patterns"
    )
    if not pat.empty:
        render_chart(bar(
            pat[pat["symptom"] != "Wartung/Installation"], x="shotgun_pct", y="symptom",
            labels={"shotgun_pct": "Shotgun-Quote (%)", "symptom": "Symptom"},
            title="Shotgun-Quote je Symptom (ohne geplante Wartung)",
        ))
        show = pat.rename(columns={
            "symptom": "Symptom", "einsaetze": "Einsätze", "schnitt_teiltypen": "Ø Teiltypen",
            "shotgun_einsaetze": "Shotgun-Einsätze", "shotgun_pct": "Shotgun %",
            "material_eur": "Material €", "haeufigste_teilkombi": "Häufigste Teil-Kombi",
        })
        st.dataframe(show, width="stretch", hide_index=True)

    st.markdown("**Aufschlüsselung: welche Teiltypen bei einem Symptom**")
    syms = pat["symptom"].tolist() if not pat.empty else []
    sym_sel = st.selectbox("Symptom wählen", options=syms or ["—"], index=0)
    bd = frame(
        "SELECT teiltyp, positionen, einsaetze, material_eur "
        "FROM insights.vw_symptom_teiltyp WHERE symptom = :s ORDER BY positionen DESC",
        {"s": sym_sel},
    )
    if not bd.empty:
        render_chart(bar(
            bd, x="positionen", y="teiltyp", top=12,
            labels={"positionen": "Positionen", "teiltyp": "Teiltyp"},
            title=f"Getauschte Teiltypen bei „{sym_sel}“",
        ))
        st.dataframe(bd.rename(columns={
            "teiltyp": "Teiltyp", "positionen": "Positionen", "einsaetze": "Einsätze",
            "material_eur": "Material €",
        }), width="stretch", hide_index=True)

    with st.expander(f"🔎 Verdachts-Einsätze bei „{sym_sel}“ (mit Ticket-Text)"):
        ex = frame(
            "SELECT datum, techniker, manufacturer_canonical AS hersteller, model_display AS modell, "
            "customer_name AS kunde, teiltypen, teiltyp_liste AS teile, material_eur, problem_text AS problem "
            "FROM insights.vw_service_visits WHERE symptom = :s AND shotgun_verdacht "
            "ORDER BY teiltypen DESC, material_eur DESC LIMIT 100",
            {"s": sym_sel},
        )
        st.write(f"**{_de(len(ex))}** Verdachts-Einsätze (max. 100)")
        st.dataframe(ex, width="stretch", hide_index=True)

# --- Tab 2: Shotgun-Einsätze (Liste) ----------------------------------------
with tab_shot:
    st.markdown("**Einsätze mit Shotgun-Verdacht** — 3+ verschiedene Teiltypen bei einer Störung "
                "(geplante Wartung ausgenommen). Spalte „Teile“ zeigt die Kombination.")
    such = st.text_input("Filter — Kunde, Modell oder Techniker (optional)", "", key="shot_q")
    clauses = ["shotgun_verdacht"]
    params: dict = {}
    if such.strip():
        clauses.append("(customer_name ILIKE :q OR model_display ILIKE :q OR techniker ILIKE :q)")
        params["q"] = f"%{such.strip()}%"
    df = frame(
        "SELECT datum, techniker, symptom, manufacturer_canonical AS hersteller, model_display AS modell, "
        "customer_name AS kunde, customer_city AS ort, teiltypen, teiltyp_liste AS teile, "
        "teile_positionen AS positionen, material_eur, problem_text AS problem "
        f"FROM insights.vw_service_visits WHERE {' AND '.join(clauses)} "
        "ORDER BY datum DESC, teiltypen DESC LIMIT 500",
        params,
    )
    st.write(f"**{_de(len(df))}** Verdachts-Einsätze (max. 500)")
    st.dataframe(df, width="stretch", hide_index=True)

# --- Tab 3: Techniker-Profil ------------------------------------------------
with tab_tech:
    st.markdown("**Shotgun-Quote je Techniker** — der direkte Schulungs-Hebel (ab 10 Einsätzen). "
                "Wartungen sind separat ausgewiesen und zählen nicht als Shotgun.")
    st.caption("Techniker erscheinen mit der pseudonymen Radix-employee_id, bis du sie in "
               "`config/technicians.yaml` Kürzeln zuordnest. Entwurf erzeugen: "
               "`python scripts/seed_technicians.py` (rät Kürzel aus dem Call-Log, mit Konfidenz). "
               f"Mehr: [Doku Service]({doc('service.md', 'techniker-zuordnung')}).")
    tech = frame(
        "SELECT techniker, einsaetze, schnitt_teiltypen, shotgun_einsaetze, shotgun_pct, "
        "wartungen, material_eur FROM insights.vw_technician_service_profile"
    )
    if not tech.empty:
        render_chart(bar(
            tech.head(20), x="shotgun_pct", y="techniker",
            labels={"shotgun_pct": "Shotgun-Quote (%)", "techniker": "Techniker"},
            title="Shotgun-Quote je Techniker (Top 20)",
        ))
        st.dataframe(tech.rename(columns={
            "techniker": "Techniker", "einsaetze": "Einsätze", "schnitt_teiltypen": "Ø Teiltypen",
            "shotgun_einsaetze": "Shotgun-Einsätze", "shotgun_pct": "Shotgun %",
            "wartungen": "Wartungen", "material_eur": "Material €",
        }), width="stretch", hide_index=True)
    st.caption("Lesehilfe: Eine hohe Shotgun-Quote bei vielen Einsätzen ist ein Schulungs-Kandidat — "
               "vor dem Gespräch einzelne Fälle im Tab „Shotgun-Einsätze“ prüfen (Kontext zählt).")
