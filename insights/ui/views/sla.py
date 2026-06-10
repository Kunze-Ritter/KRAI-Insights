"""
SLA-Dashboard — Reaktionszeiten & Ticket-Volumen.

Datenquelle: Radix (crawl_radix_tickets) — Erstellzeit + Kategorie pro Ticket.
Abschlusszeit = letzte Aktivität in activity_notes (Migration 072).
Priorität A = Blockierend (gleicher Tag gilt als eingehalten, Näherung).
Priorität B = alle Störungen, Ziel: bis nächster Arbeitstag (NBD, ≤1 Tag).
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from insights.core.db import insights_engine
from insights.ui.links import doc
from insights.ui.theme import setup_page
from sqlalchemy import text

_PRIORITY_FARBEN = {"A": "#e74c3c", "B": "#e67e22", "C": "#3498db"}
_KATEGORIE_FARBEN = {
    "Störung": "#e74c3c",
    "Wartung": "#2ecc71",
    "Installation": "#3498db",
    "Support": "#9b59b6",
    "Sonstiges": "#95a5a6",
}


@st.cache_data(ttl=300)
def _frame(sql: str, params: dict | None = None) -> pd.DataFrame:
    with insights_engine().connect() as conn:
        return pd.DataFrame(conn.execute(text(sql), params or {}).mappings().all())


@st.cache_data(ttl=300)
def _ticket_count() -> int:
    with insights_engine().connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM insights.radix_tickets")).scalar()
        return int(n or 0)


setup_page(
    "📊 SLA & Reaktionszeiten",
    "Ticket-Volumen nach Dringlichkeit, durchschnittliche Wiederherstellungszeiten "
    "und SLA-Einhalte-Quote — monatliche Übersicht.",
)
st.caption(f"📖 Methodik: [Doku SLA]({doc('sla.md')})")

ticket_count = _ticket_count()
if ticket_count == 0:
    st.warning(
        "**Keine Ticket-Daten geladen.** Bitte zuerst den ETL-Lauf starten:  \n"
        "```\ndocker exec krai-insights-app python -m insights.etl.load --radix-tickets\n```"
    )
    st.stop()

with st.expander("📌 Was zeigt dieses Dashboard? Datenquelle & Hinweise"):
    st.markdown(
        "**Was ist ein SLA?** Ein Service Level Agreement (SLA) ist eine Vereinbarung, "
        "innerhalb welcher Zeit KR auf einen Serviceauftrag reagiert und das Gerät "
        "wiederherstellt:  \n"
        "- **Störung A (Blockierend):** Gerät steht komplett — Ziel: **innerhalb 8 Stunden** "
        "nach Auftragseingang.  \n"
        "- **Störung B (Nicht blockierend):** Gerät läuft eingeschränkt — Ziel: **bis zum "
        "nächsten Arbeitstag (NBD)**.  \n"
        "- **Priorität C:** Geplante Wartung, Installation, Support — kein SLA-Ziel.  \n\n"
        "**Datenquelle:** Radix-Tickets (Erstellzeit = `documentDate`); Abschlusszeit = "
        "letzte Aktivität im Ticket aus dem Ticket-Crawl.  \n\n"
        "**Hinweis zur Genauigkeit:** Die Erledigung wird tagesgenau erfasst. Das SLA A "
        "(8 Stunden) ist daher eine **Näherung**: Tickets, die am selben Tag eröffnet und "
        "abgeschlossen wurden, gelten als eingehalten. Für stundenbasierte Präzision wird "
        "`activity_datetime` bei neuen Crawls befüllt — alte Daten bleiben taggenau.  \n\n"
        "**Geschäftszeiten:** Mo-Fr 7:30-17:30 Uhr (werden in dieser Version noch nicht "
        "herausgerechnet)."
    )

# --- Jahresfilter ---
jahre_df = _frame(
    "SELECT DISTINCT DATE_PART('year', created_at)::INT AS jahr "
    "FROM insights.radix_tickets WHERE created_at IS NOT NULL "
    "ORDER BY 1 DESC LIMIT 10"
)
jahre = sorted(jahre_df["jahr"].dropna().astype(int).tolist(), reverse=True)
col_j1, col_j2 = st.columns([1, 3])
with col_j1:
    if jahre:
        sel_jahr = st.selectbox("Jahr", jahre, index=0)
    else:
        sel_jahr = 2025

# --- Kennzahlen-Zeile ---
kz = _frame(
    """
    SELECT
        COUNT(*) FILTER (WHERE priority_code = 'A') AS stoerung_a,
        COUNT(*) FILTER (WHERE priority_code = 'B') AS stoerung_b,
        COUNT(*) FILTER (WHERE priority_code = 'C') AS andere,
        ROUND(100.0 * COUNT(*) FILTER (WHERE sla_met = true AND priority_code = 'A')
              / NULLIF(COUNT(*) FILTER (WHERE sla_met IS NOT NULL AND priority_code = 'A'), 0), 1
        ) AS sla_a_pct,
        ROUND(100.0 * COUNT(*) FILTER (WHERE sla_met = true AND priority_code = 'B')
              / NULLIF(COUNT(*) FILTER (WHERE sla_met IS NOT NULL AND priority_code = 'B'), 0), 1
        ) AS sla_b_pct,
        ROUND(AVG(recovery_hours) FILTER (WHERE priority_code = 'A' AND recovery_hours IS NOT NULL), 1) AS avg_h_a,
        ROUND(AVG(recovery_hours) FILTER (WHERE priority_code = 'B' AND recovery_hours IS NOT NULL), 1) AS avg_h_b
    FROM insights.vw_sla_tickets
    WHERE DATE_PART('year', created_at) = :jahr
    """,
    {"jahr": sel_jahr},
)
if not kz.empty:
    r = kz.iloc[0]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Störung A (gesamt)", f"{int(r.get('stoerung_a') or 0):,}".replace(",", "."),
              help="Blockierende Störungen im gewählten Jahr")
    c2.metric("Störung B (gesamt)", f"{int(r.get('stoerung_b') or 0):,}".replace(",", "."),
              help="Nicht-blockierende Störungen + andere Störungsarten")
    sla_a = r.get("sla_a_pct")
    sla_b = r.get("sla_b_pct")
    c3.metric("SLA A-Quote", f"{sla_a} %" if sla_a is not None else "-",
              help="Anteil Störung-A-Tickets, die tagesgenau am gleichen Tag erledigt wurden (Näherung 8h)")
    c4.metric("SLA B-Quote", f"{sla_b} %" if sla_b is not None else "-",
              help="Anteil Störung-B-Tickets, die bis zum nächsten Tag erledigt wurden (NBD)")
    avg_a = r.get("avg_h_a")
    avg_b = r.get("avg_h_b")
    c5.metric(
        "Ø Reaktionszeit",
        f"A: {avg_a}h  B: {avg_b}h" if avg_a and avg_b else "-",
        help="Durchschnittliche Stunden von Erstellung bis letzter Aktivität",
    )

st.divider()

# === CHART 1: Tickets nach Dringlichkeit (monatliches Stapelbalken) ===
st.subheader("Tickets nach Dringlichkeit")
st.caption(
    "Wie viele Tickets (A=Blockierend, B=Nicht blockierend, C=Wartung/Installation/Support) "
    "wurden pro Monat neu eröffnet?"
)
vol_df = _frame(
    """
    SELECT monat, priority_code AS prioritaet, SUM(anzahl) AS anzahl
    FROM insights.vw_ticket_volume_monthly
    WHERE DATE_PART('year', monat) = :jahr
    GROUP BY monat, priority_code
    ORDER BY monat, prioritaet
    """,
    {"jahr": sel_jahr},
)
if not vol_df.empty:
    vol_df["monat"] = pd.to_datetime(vol_df["monat"])
    fig = px.bar(
        vol_df,
        x="monat", y="anzahl", color="prioritaet",
        color_discrete_map=_PRIORITY_FARBEN,
        labels={"monat": "Monat", "anzahl": "Tickets", "prioritaet": "Dringlichkeit"},
        barmode="stack",
        category_orders={"prioritaet": ["A", "B", "C"]},
    )
    fig.update_layout(xaxis_tickformat="%b %Y", legend_title="Dringlichkeit")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info(f"Keine Ticket-Daten für {sel_jahr}.")

# === CHART 2: Wiederherstellungszeit Störungen ===
st.subheader("Wiederherstellungszeit Störungen")
st.caption(
    "Durchschnittliche Stunden von Ticketerstellung bis Abschluss — "
    "nur erledigte Störungen (A+B). Tagesgenaue Naeherung: letzter Tag, Fallback 17:00 Uhr."
)
rtz_df = _frame(
    """
    SELECT monat, priority_code AS prioritaet,
           avg_recovery_stunden AS stunden,
           gesamt, eingehalten
    FROM insights.vw_sla_compliance
    WHERE DATE_PART('year', monat) = :jahr
    ORDER BY monat, prioritaet
    """,
    {"jahr": sel_jahr},
)
if not rtz_df.empty:
    rtz_df["monat"] = pd.to_datetime(rtz_df["monat"])
    fig2 = px.bar(
        rtz_df,
        x="monat", y="stunden", color="prioritaet",
        color_discrete_map=_PRIORITY_FARBEN,
        barmode="group",
        labels={"monat": "Monat", "stunden": "Ø Stunden", "prioritaet": "Dringlichkeit"},
        text_auto=".0f",
    )
    # SLA-Linien als horizontale Referenzen
    fig2.add_hline(y=8, line_dash="dot", line_color="#e74c3c",
                   annotation_text="SLA A: 8h", annotation_position="top left")
    fig2.add_hline(y=24, line_dash="dot", line_color="#e67e22",
                   annotation_text="SLA B: NBD (24h)", annotation_position="top left")
    fig2.update_layout(xaxis_tickformat="%b %Y", legend_title="Dringlichkeit")
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info(f"Keine SLA-Daten für {sel_jahr} (Tickets ggf. noch nicht abgeschlossen).")

# === CHART 3: Tickets nach Ticketarten ===
st.subheader("Tickets nach Ticketart")
st.caption(
    "Aufschlüsselung nach Ticket-Kategorie aus der Wartungsart (maintenanceType): "
    "Störung, Wartung (geplant), Installation/Abholung, Support."
)
kat_df = _frame(
    """
    SELECT monat, ticket_category AS kategorie, SUM(anzahl) AS anzahl
    FROM insights.vw_ticket_volume_monthly
    WHERE DATE_PART('year', monat) = :jahr
    GROUP BY monat, ticket_category
    ORDER BY monat, ticket_category
    """,
    {"jahr": sel_jahr},
)
if not kat_df.empty:
    kat_df["monat"] = pd.to_datetime(kat_df["monat"])
    fig3 = px.bar(
        kat_df,
        x="monat", y="anzahl", color="kategorie",
        color_discrete_map=_KATEGORIE_FARBEN,
        labels={"monat": "Monat", "anzahl": "Tickets", "kategorie": "Ticketart"},
        barmode="stack",
        category_orders={"kategorie": ["Störung", "Wartung", "Installation", "Support", "Sonstiges"]},
    )
    fig3.update_layout(xaxis_tickformat="%b %Y", legend_title="Ticketart")
    st.plotly_chart(fig3, use_container_width=True)
else:
    st.info(f"Keine Daten für {sel_jahr}.")

# === CHART 4: SLA-Einhaltung (Gesamt-Übersicht) ===
st.subheader("SLA-Einhaltung (Jahres-Übersicht)")
st.caption(
    "Gesamtquote im gewählten Jahr: Anteil der erledigten Störungs-Tickets, "
    "die das SLA-Ziel eingehalten haben."
)
sla_gesamt = _frame(
    """
    SELECT priority_code AS prioritaet,
           SUM(gesamt) AS gesamt,
           SUM(eingehalten) AS eingehalten,
           SUM(gesamt) - SUM(eingehalten) AS ueberschritten,
           ROUND(100.0 * SUM(eingehalten) / NULLIF(SUM(gesamt), 0), 1) AS quote
    FROM insights.vw_sla_compliance
    WHERE DATE_PART('year', monat) = :jahr
    GROUP BY priority_code
    ORDER BY priority_code
    """,
    {"jahr": sel_jahr},
)
if not sla_gesamt.empty:
    col_a, col_b = st.columns(2)
    for _, row in sla_gesamt.iterrows():
        prio = row["prioritaet"]
        gesamt = int(row.get("gesamt") or 0)
        eingehalten = int(row.get("eingehalten") or 0)
        ueberschritten = int(row.get("ueberschritten") or 0)
        quote = float(row.get("quote") or 0)
        ziel = "8h (tagesgen. Näherung)" if prio == "A" else "NBD"
        container = col_a if prio == "A" else col_b
        with container:
            st.metric(
                f"SLA {prio} — {ziel}",
                f"{quote} %",
                delta=f"{eingehalten} von {gesamt} Tickets eingehalten",
                delta_color="normal",
            )
            # Mini-Balken
            if gesamt > 0:
                df_mini = pd.DataFrame({
                    "Status": ["Eingehalten", "Überschritten"],
                    "Tickets": [eingehalten, ueberschritten],
                })
                fig_mini = px.bar(
                    df_mini, x="Tickets", y="Status",
                    color="Status",
                    color_discrete_map={"Eingehalten": "#2ecc71", "Überschritten": "#e74c3c"},
                    orientation="h", text_auto=True,
                )
                fig_mini.update_layout(
                    showlegend=False,
                    height=150,
                    margin={"t": 10, "b": 10, "l": 0, "r": 0},
                    xaxis_title="", yaxis_title="",
                )
                st.plotly_chart(fig_mini, use_container_width=True)
else:
    st.info(f"Keine SLA-Auswertung für {sel_jahr} — Tickets ggf. noch nicht abgeschlossen.")

# === DETAIL-TABELLE ===
st.divider()
with st.expander("🔍 Detail-Ansicht: Störungs-Tickets mit SLA-Bewertung"):
    such = st.text_input("Kundenname oder Ticket-Code filtern (optional)", "")
    clauses = ["DATE_PART('year', created_at) = :jahr", "priority_code IN ('A', 'B')"]
    params: dict = {"jahr": sel_jahr}
    if such.strip():
        clauses.append("(customer_name ILIKE :q OR ticket_code ILIKE :q)")
        params["q"] = f"%{such.strip()}%"
    df_detail = _frame(
        f"""
        SELECT
            ticket_code AS "Ticket",
            created_at::DATE AS "Erstellt",
            closed_ts::DATE AS "Erledigt",
            recovery_hours AS "Stunden",
            recovery_days AS "Tage",
            CASE sla_met WHEN true THEN 'ja' WHEN false THEN 'nein' ELSE '-' END AS "SLA",
            priority_code AS "Prio",
            ticket_category AS "Kategorie",
            customer_name AS "Kunde",
            maintenance_type AS "Wartungsart"
        FROM insights.vw_sla_tickets
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC
        LIMIT 500
        """,
        params,
    )
    st.write(f"**{len(df_detail):,}** Störungs-Tickets (max. 500)".replace(",", "."))
    st.dataframe(df_detail, hide_index=True)
