"""
Service — Teile-Einsatz & Schulung („Shotgun-Reparatur" aufdecken).

Findet Muster, wo bei einem Einsatz auf Verdacht viele Teile (Trommel, Entwickler,
Transfer, Fixierer …) auf einmal getauscht werden, statt gezielt — um Techniker zu
schulen. Geplante Wartung/Installation (Teile-Kit korrekt) ist ausgenommen.

Interaktiv: Tabellen-Zeilen sind anklickbar (Drilldown). Im Techniker-Profil öffnet ein
Klick das Detail mit Symptom-Vergleich zum Team + echten Tickets; ein Klick auf einen
Einsatz zeigt das volle Ticket. Quelle: vw_service_visits & Co. (Migration 066-070).
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


def _click(df_display: pd.DataFrame, key: str) -> int | None:
    """Render a selectable table; return the selected row index (or None)."""
    ev = st.dataframe(df_display, width="stretch", hide_index=True,
                      on_select="rerun", selection_mode="single-row", key=key)
    rows = ev.selection.rows
    return rows[0] if rows else None


def _visit_table(df: pd.DataFrame, key: str) -> str | None:
    """Selectable visit table. `df` carries radix_activity_id (hidden, for lookup) +
    readable radix_ticket/radix_vorgang. Returns the selected activity_id or None."""
    disp = df.rename(columns={"radix_ticket": "Radix-Ticket", "radix_vorgang": "Radix-Vorgang"})
    disp = disp.drop(columns=[c for c in ("radix_activity_id",) if c in disp.columns])
    i = _click(disp, key=key)
    return str(df.iloc[i]["radix_activity_id"]) if i is not None else None


def ticket_detail(aid: str) -> None:
    """Volles Ticket: Metadaten, getauschte Teile (mit Preis), Problem- + Technik-Text."""
    v = frame(
        "SELECT datum, customer_name, customer_city, manufacturer_canonical, model_display, "
        "techniker, dispo, team, symptom, material_eur, arbeit_min, problem_text, technik_text, "
        "radix_ticket, radix_vorgang, device_serial FROM insights.vw_service_visits "
        "WHERE radix_activity_id = :a", {"a": aid},
    )
    if v.empty:
        st.info("Keine Details zu diesem Ticket.")
        return
    r = v.iloc[0]
    tic, vor = r["radix_ticket"] or "—", r["radix_vorgang"] or "—"
    st.markdown(f"#### 🎫 Radix-Ticket `{tic}` · Vorgang `{vor}` · {r['datum']}")
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"**Kunde:** {r['customer_name'] or '—'} ({r['customer_city'] or '—'})")
    geraet = f"{r['manufacturer_canonical'] or '—'} {r['model_display'] or ''}"
    c1.markdown(f"**Gerät:** {geraet} · SN {r['device_serial'] or '—'}")
    c2.markdown(f"**Techniker:** {r['techniker'] or '—'}")
    c2.markdown(f"**Dispo:** {r['dispo'] or '—'} · Team {r['team'] or '—'}")
    c3.markdown(f"**Symptom:** {r['symptom']}")
    c3.markdown(f"**Material:** {_de(r['material_eur'] or 0)} € · Arbeit {int(r['arbeit_min'] or 0)} min")
    parts = frame(
        "SELECT description AS teil, quantity AS menge, unit_price AS einzelpreis_eur, "
        "total_eur AS summe_eur, invoicing_type AS abrechnung "
        "FROM insights.cost_events WHERE radix_activity_id = :a AND cost_type = 'material' "
        "ORDER BY total_eur DESC NULLS LAST", {"a": aid},
    )
    st.markdown("**Getauschte Teile:**")
    st.dataframe(parts, width="stretch", hide_index=True)
    if r["problem_text"]:
        st.markdown("**Problem (Ticket):**")
        st.text(r["problem_text"])
    if r["technik_text"]:
        st.markdown("**Technik (Verlauf):**")
        st.text(r["technik_text"])


def technician_detail(t: str) -> None:
    """Techniker-Detail: Symptom-Vergleich zum Team, Signatur-Kombis, anklickbare Tickets."""
    st.markdown(f"### 👤 {t}")
    peer = frame(
        "WITH s AS (SELECT symptom, count(*) n, count(*) FILTER (WHERE shotgun_verdacht) sg, "
        "avg(teiltypen) sp FROM insights.vw_service_visits "
        "WHERE techniker = :t AND symptom <> 'Wartung/Installation' GROUP BY symptom), "
        "o AS (SELECT symptom, avg(teiltypen) ko FROM insights.vw_service_visits "
        "WHERE techniker <> :t AND symptom <> 'Wartung/Installation' GROUP BY symptom) "
        "SELECT s.symptom, s.n AS einsaetze, s.sg AS shotgun, round(s.sp, 2) AS ich_teile, "
        "round(o.ko, 2) AS team_teile, round(s.sp - o.ko, 2) AS differenz "
        "FROM s LEFT JOIN o USING (symptom) ORDER BY s.n DESC", {"t": t},
    )
    if not peer.empty:
        st.markdown("**Teile je Einsatz — er/sie vs. Team** (nur Reparatur; Differenz > 0 = mehr als das Team):")
        render_chart(bar(
            peer[peer["differenz"].notna()], x="differenz", y="symptom",
            labels={"differenz": "Mehr-Teile vs. Team", "symptom": "Symptom"},
            title=f"{t}: Mehrverbrauch an Teiltypen je Symptom",
        ))
        st.dataframe(peer.rename(columns={
            "symptom": "Symptom", "einsaetze": "Einsätze", "shotgun": "Shotgun",
            "ich_teile": "Ø Teile (er/sie)", "team_teile": "Ø Teile (Team)", "differenz": "Differenz",
        }), width="stretch", hide_index=True)

    combos = frame(
        "SELECT teiltyp_liste AS kombi, count(*) AS anzahl, round(sum(material_eur)) AS material_eur "
        "FROM insights.vw_service_visits WHERE techniker = :t AND shotgun_verdacht "
        "GROUP BY teiltyp_liste ORDER BY anzahl DESC LIMIT 10", {"t": t},
    )
    if not combos.empty:
        st.markdown("**Signatur-Teilkombis** (auf den Shotgun-Einsätzen):")
        st.dataframe(combos.rename(columns={
            "kombi": "Teil-Kombination", "anzahl": "Anzahl", "material_eur": "Material €",
        }), width="stretch", hide_index=True)

    ex = frame(
        "SELECT radix_activity_id, radix_ticket, radix_vorgang, datum, symptom, model_display AS modell, "
        "customer_name AS kunde, teiltypen, teiltyp_liste AS teile, material_eur "
        "FROM insights.vw_service_visits WHERE techniker = :t AND shotgun_verdacht "
        "ORDER BY teiltypen DESC, datum DESC LIMIT 50", {"t": t},
    )
    if not ex.empty:
        st.markdown("**Verdachts-Einsätze — Zeile anklicken für das ganze Ticket:**")
        aid = _visit_table(ex, key=f"texsel::{t}")
        if aid:
            ticket_detail(aid)


setup_page(
    "🧰 Service — Teile-Einsatz & Schulung",
    "Wo werden bei einem Einsatz auf Verdacht zu viele Teile getauscht? Muster finden, "
    "um Techniker gezielt zu schulen. Geplante Wartung/Installation ist ausgenommen.",
)
st.caption(f"📖 Methodik & Definitionen: [Doku Service]({doc('service.md')})  ·  "
           "💡 Tabellen-Zeilen sind anklickbar — für das volle Ticket bzw. das Techniker-Detail.")

with st.expander("📌 Was ist eine 'Shotgun-Reparatur' und woher kommen die Daten?"):
    st.markdown(
        "**Was ist das Problem?** Bei manchen Einsätzen tauscht ein Techniker mehrere teure Teile "
        "auf einmal (z. B. Bildtrommel + Entwicklereinheit + Transferband + Fixiereinheit), "
        "weil er nicht sicher ist, was genau den Fehler verursacht. Das nennt sich 'Shotgun-Reparatur' "
        "— wie mit einer Schrotflinte schießen und hoffen, dass etwas trifft. "
        "Problem: oft war nur ein einziges Teil defekt, der Rest war unnötig und kostet KR Geld.  \n\n"
        "**Wie wird das erkannt?** Das System zählt, wie viele **verschiedene Teiltypen** pro Einsatz "
        "eingebaut wurden. Ab **3 verschiedenen Teiltypen** bei einer Reparatur (nicht Wartung) "
        "gilt ein Einsatz als Verdacht.  \n\n"
        "**Wichtig:** Geplante Wartungen (PM, Wartungskit, Reinigung) sind **ausgenommen** — "
        "dort ist der gleichzeitige Teile-Tausch korrekt und gewollt.  \n\n"
        "**Daten kommen aus:** Service-System Radix — eingebaute Teile mit Preisen und "
        "Ticket-Texte mit Fehlerbeschreibung und Techniker-Notizen.  \n\n"
        "**Was sollte ich tun?**  \n"
        "→ Tab **Überblick**: Techniker mit auffällig vielen Shotgun-Einsätzen identifizieren.  \n"
        "→ Tab **Techniker-Profil**: Klick auf einen Namen zeigt, bei welchen Symptomen er/sie "
        "mehr Teile als der Teamschnitt tauscht — gute Grundlage für ein Schulungsgespräch.  \n"
        "→ Tab **Symptom-Muster**: Welche Fehlermeldungen führen besonders oft zu Mehrfach-Tausch? "
        "Das zeigt, wo Diagnose-Leitfäden helfen würden.  \n"
        "→ Tab **Einsatz-Details**: Einzelne Tickets einsehen (Klick auf eine Zeile)."
    )

kpi = frame(
    "SELECT count(*) AS einsaetze, count(*) FILTER (WHERE shotgun_verdacht) AS shotgun, "
    "round(avg(teiltypen), 2) AS schnitt, "
    "round(sum(material_eur) FILTER (WHERE shotgun_verdacht)) AS shotgun_eur "
    "FROM insights.vw_service_visits WHERE symptom <> 'Wartung/Installation'"
)
if not kpi.empty:
    r = kpi.iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reparatur-Einsätze (mit Teilen)", _de(r["einsaetze"] or 0))
    c2.metric("Shotgun-Verdacht (≥3 Teiltypen)", _de(r["shotgun"] or 0),
              help="Einsätze mit 3+ verschiedenen Teiltypen, die KEINE geplante Wartung/PM sind.")
    c3.metric("Ø Teiltypen je Einsatz", f"{r['schnitt'] or 0}")
    c4.metric("Material-€ auf Verdachts-Einsätzen", _de(r["shotgun_eur"] or 0) + " €",
              help="Material auf den Verdachts-Einsätzen — Hinweis auf mögliche Über-Tausche, "
                   "kein bewiesener Verlust.")

st.divider()
tab_tech, tab_sym, tab_shot = st.tabs(
    ["👷 Techniker-Profil", "🎯 Symptom → Teil-Muster", "🧰 Shotgun-Einsätze"]
)

# --- Tab: Techniker-Profil (mit Drilldown) ----------------------------------
with tab_tech:
    st.markdown("**Shotgun-Quote je Techniker** (ab 10 Einsätzen). **Zeile anklicken** öffnet das "
                "Detail: Symptom-Vergleich zum Team, Signatur-Kombis und echte Tickets.")
    st.caption("Techniker = der **ausführende** Mitarbeiter aus Radix (`employee`), nicht der "
               f"Verantwortliche/Dispo. Mehr: [Doku Service]({doc('service.md', 'techniker-zuordnung')}).")
    tech = frame(
        "SELECT techniker, team, einsaetze, schnitt_teiltypen, shotgun_einsaetze, shotgun_pct, "
        "wartungen, material_eur FROM insights.vw_technician_service_profile"
    )
    if not tech.empty:
        tdisp = tech.rename(columns={
            "techniker": "Techniker", "team": "Team", "einsaetze": "Einsätze",
            "schnitt_teiltypen": "Ø Teiltypen", "shotgun_einsaetze": "Shotgun-Einsätze",
            "shotgun_pct": "Shotgun %", "wartungen": "Wartungen", "material_eur": "Material €",
        })
        i = _click(tdisp, key="tech_profile")
        if i is not None:
            st.divider()
            technician_detail(str(tech.iloc[i]["techniker"]))
        else:
            st.caption("⬆️ Eine Zeile anklicken, um das Techniker-Detail zu öffnen.")

# --- Tab: Symptom -> Teil-Muster --------------------------------------------
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
        st.dataframe(pat.rename(columns={
            "symptom": "Symptom", "einsaetze": "Einsätze", "schnitt_teiltypen": "Ø Teiltypen",
            "shotgun_einsaetze": "Shotgun-Einsätze", "shotgun_pct": "Shotgun %",
            "material_eur": "Material €", "haeufigste_teilkombi": "Häufigste Teil-Kombi",
        }), width="stretch", hide_index=True)

    syms = pat["symptom"].tolist() if not pat.empty else []
    sym_sel = st.selectbox("Symptom für die Aufschlüsselung wählen", options=syms or ["—"], index=0)
    bd = frame(
        "SELECT teiltyp, positionen, einsaetze, material_eur "
        "FROM insights.vw_symptom_teiltyp WHERE symptom = :s ORDER BY positionen DESC", {"s": sym_sel},
    )
    if not bd.empty:
        render_chart(bar(
            bd, x="positionen", y="teiltyp", top=12,
            labels={"positionen": "Positionen", "teiltyp": "Teiltyp"},
            title=f"Getauschte Teiltypen bei „{sym_sel}“",
        ))
    ex = frame(
        "SELECT radix_activity_id, radix_ticket, radix_vorgang, datum, techniker, "
        "manufacturer_canonical AS hersteller, model_display AS modell, customer_name AS kunde, "
        "teiltypen, teiltyp_liste AS teile, material_eur "
        "FROM insights.vw_service_visits WHERE symptom = :s AND shotgun_verdacht "
        "ORDER BY teiltypen DESC, material_eur DESC LIMIT 100", {"s": sym_sel},
    )
    st.markdown(f"**Verdachts-Einsätze bei „{sym_sel}“ — Zeile anklicken für das ganze Ticket:**")
    st.write(f"{_de(len(ex))} Einsätze (max. 100)")
    if not ex.empty:
        aid = _visit_table(ex, key="sym_visits")
        if aid:
            ticket_detail(aid)

# --- Tab: Shotgun-Einsätze (Liste, anklickbar) ------------------------------
with tab_shot:
    st.markdown("**Alle Einsätze mit Shotgun-Verdacht** (3+ Teiltypen bei einer Störung, geplante "
                "Wartung/PM ausgenommen). **Zeile anklicken** zeigt das ganze Ticket.")
    such = st.text_input("Filter — Kunde, Modell, Techniker oder Symptom (optional)", "", key="shot_q")
    clauses = ["shotgun_verdacht"]
    params: dict = {}
    if such.strip():
        clauses.append("(customer_name ILIKE :q OR model_display ILIKE :q OR techniker ILIKE :q OR symptom ILIKE :q)")
        params["q"] = f"%{such.strip()}%"
    df = frame(
        "SELECT radix_activity_id, radix_ticket, radix_vorgang, datum, techniker, dispo, symptom, "
        "manufacturer_canonical AS hersteller, model_display AS modell, customer_name AS kunde, "
        "teiltypen, teiltyp_liste AS teile, material_eur "
        f"FROM insights.vw_service_visits WHERE {' AND '.join(clauses)} "
        "ORDER BY datum DESC, teiltypen DESC LIMIT 500", params,
    )
    st.write(f"**{_de(len(df))}** Verdachts-Einsätze (max. 500)")
    if not df.empty:
        aid = _visit_table(df, key="shot_visits")
        if aid:
            ticket_detail(aid)
