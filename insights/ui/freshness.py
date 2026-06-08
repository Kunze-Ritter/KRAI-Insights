"""
Daten-Frische + letzter ETL-Lauf fuer das Dashboard.

Liest die Observability-Views aus Migration 064 (``vw_table_freshness`` /
``vw_etl_status``) und macht zwei Dinge sichtbar, die bisher nur im Scheduler-Log
standen: (a) ist eine Kerntabelle veraltet (Nightly ausgefallen?), (b) hatte der
letzte Lauf fehlgeschlagene Schritte. ``render_banner()`` zeigt NUR bei Problemen
einen roten Banner (sonst nichts, damit der Alltag ruhig bleibt); ``data_stand()``
liefert den juengsten Daten-Stand fuer die Fussnote.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text

from insights.core.db import insights_engine
from insights.ui.links import doc


@st.cache_data(ttl=300)
def _freshness() -> pd.DataFrame:
    try:
        with insights_engine().connect() as conn:
            return pd.DataFrame(conn.execute(text(
                "SELECT tabelle, kadenz, letzter_stand, alter_stunden, max_stunden, status "
                "FROM insights.vw_table_freshness ORDER BY status, tabelle"
            )).mappings().all())
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def _etl_status() -> pd.DataFrame:
    try:
        with insights_engine().connect() as conn:
            return pd.DataFrame(conn.execute(text(
                "SELECT pipeline, lauf_start, lauf_ende, schritte, schritte_ok, "
                "schritte_fehler, schritte_laufend, fehler_schritte "
                "FROM insights.vw_etl_status ORDER BY pipeline"
            )).mappings().all())
    except Exception:
        return pd.DataFrame()


def render_banner() -> None:
    """Roter Banner NUR bei Problemen: veraltete/leere Tabelle ODER letzter Nightly mit Fehler."""
    fr = _freshness()
    et = _etl_status()
    probleme: list[str] = []

    if not fr.empty:
        for _, r in fr[fr["status"].isin(["veraltet", "leer"])].iterrows():
            if r["status"] == "leer":
                probleme.append(f"Tabelle „{r['tabelle']}“ ist leer (nie geladen)")
            else:
                probleme.append(
                    f"Tabelle „{r['tabelle']}“ ist veraltet "
                    f"({int(r['alter_stunden'])} h alt, erwartet < {int(r['max_stunden'])} h)"
                )

    if not et.empty:
        for _, r in et[et["schritte_fehler"].fillna(0) > 0].iterrows():
            probleme.append(
                f"Letzter {r['pipeline']}-Lauf: {int(r['schritte_fehler'])} Schritt(e) fehlgeschlagen "
                f"({r['fehler_schritte']})"
            )

    if probleme:
        st.error(
            "⚠️ **Daten-Aktualität:** " + " · ".join(probleme)
            + f"  \nDetails und Bedeutung: [Observability-Doku]({doc('observability.md')}).",
            icon="⚠️",
        )


def data_stand() -> str | None:
    """Juengster Daten-Stand ueber alle Kerntabellen (für die Fussnote), oder None."""
    fr = _freshness()
    if fr.empty or fr["letzter_stand"].dropna().empty:
        return None
    ts = pd.to_datetime(fr["letzter_stand"], utc=True, errors="coerce").max()
    return None if pd.isna(ts) else ts.strftime("%Y-%m-%d %H:%M UTC")


def render_status_detail() -> None:
    """Detail-Tabellen (Frische je Tabelle + letzter Lauf je Pipeline) für einen Expander."""
    fr = _freshness()
    if not fr.empty:
        st.dataframe(
            fr.rename(columns={
                "tabelle": "Tabelle", "kadenz": "Kadenz", "letzter_stand": "Letzter Stand",
                "alter_stunden": "Alter (h)", "max_stunden": "Schwelle (h)", "status": "Status",
            }),
            width="stretch", hide_index=True,
        )
    et = _etl_status()
    if not et.empty:
        st.caption("Letzter Lauf je Pipeline:")
        st.dataframe(
            et.rename(columns={
                "pipeline": "Pipeline", "lauf_start": "Start", "lauf_ende": "Ende",
                "schritte": "Schritte", "schritte_ok": "OK", "schritte_fehler": "Fehler",
                "schritte_laufend": "Laufend", "fehler_schritte": "Fehler-Schritte",
            }),
            width="stretch", hide_index=True,
        )
    else:
        st.caption("Noch kein Scheduler-Lauf protokolliert (vw_etl_status leer).")
