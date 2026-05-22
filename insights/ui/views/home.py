"""Übersicht — Wert-Board: die wichtigsten Punkte zum Handeln auf einen Blick."""

from __future__ import annotations

import streamlit as st
from insights.core.config import get_settings
from insights.core.db import insights_engine
from sqlalchemy import text

settings = get_settings()


def _eur(n: float | int) -> str:
    return f"{round(n):,}".replace(",", ".") + " €"


def _de(n: float | int) -> str:
    return f"{round(n):,}".replace(",", ".")


@st.cache_data(ttl=300)
def lagebericht() -> dict:
    try:
        with insights_engine().connect() as conn:
            row = conn.execute(text("SELECT * FROM insights.vw_lagebericht")).mappings().first()
        return dict(row) if row else {}
    except Exception:
        return {}


st.title("📊 KRAI Insights")
st.caption("Was die Daten gerade hergeben — die wichtigsten Punkte zum Handeln. "
           "Für konkrete Fragen den Assistenten (Seite Fragen) nutzen.")

k = lagebericht()
if not k:
    st.info("Kennzahlen derzeit nicht verfügbar — bitte Datenbank-Verbindung prüfen.")
    st.stop()

claims = int(k.get("garantie_claims") or 0)
preis = int(k.get("toner_preis_median") or 0)
schaetz = claims * preis

# --- Hero: Geld zurückholen (Garantie) -------------------------------------
st.subheader("💰 Geld zurückholen — Garantie")
c1, c2, c3 = st.columns(3)
c1.metric("Geschätztes Rückhol-Potenzial", _eur(schaetz),
          help=f"Grobe Schätzung: {_de(claims)} reklamierbare Fälle x ~{preis} € mittlerer Tonerpreis. "
               "Nur wo Preise bekannt sind; dient der Größenordnung.")
c2.metric("Reklamierbare Garantiefälle", _de(claims),
          help="Serial-belegt: Material innerhalb 1 Jahr UND deutlich unter Soll-Laufleistung.")
c3.metric("Verhandlungs-Kandidaten", _de(int(k.get("verhandlung_kandidaten") or 0)),
          help="Über 1 Jahr, aber unter Soll-Laufleistung — Hebel gegenüber dem Hersteller.")
st.caption(
    f"Die Garantiefälle erreichten im Schnitt nur **{int(k.get('claim_schnitt_pct') or 0)} %** der "
    "Hersteller-Soll-Laufleistung — jeder Fall ist über die Material-Seriennummer belegt. "
    "Konkrete Liste: Seite Verbrauchsmaterial → Garantie-Bewertung, oder den Assistenten fragen."
)

st.divider()

# --- Service & Datenqualität ------------------------------------------------
st.subheader("🛠️ Service & Datenqualität")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Still & unter Vertrag", _de(int(k.get("stille_unter_vertrag") or 0)),
          help="Geräte unter Vertrag, die keine Zähler mehr melden → Abrechnung läuft auf Schätzwerten. "
               "Seite: Datenqualität → Abrechnungs-Risiko.")
c2.metric("Kundenzuordnung prüfen", _de(int(k.get("kunden_abweichung") or 0)),
          help="Gerät hat in FleetMgmt und Radix verschiedene Kunden → Toner-Fehlversand-Risiko. "
               "Seite: Datenqualität → Kunden-Abgleich.")
c3.metric("Verbrauch in 14 Tagen fällig", _de(int(k.get("verbrauch_14d") or 0)),
          help="Toner/Teile, die bald leer sind → Liefer-/Tourenplanung. Seite: Verbrauchsmaterial.")
c4.metric("Auffällige Geräte", _de(int(k.get("problem_geraete") or 0)),
          help="Sehr viele Alarme (defekte Sensoren / wiederkehrende Störungen). Seite: Service-Qualität.")

st.divider()

# --- Assistent als Haupteinstieg -------------------------------------------
st.subheader("💬 Frag den Assistenten")
st.markdown(
    "Der Assistent trägt die Daten zusammen und wertet sie aus — frag einfach in normaler Sprache:\n"
    "- *Gib mir einen Überblick — wo können wir Geld zurückholen?*\n"
    "- *Garantie-Übersicht nach Hersteller*\n"
    "- *Welche Geräte unter Vertrag melden nichts?*\n"
    "- *Wo stimmt die Kundenzuordnung nicht?*\n"
    "- *Welcher Toner ist bei Stadt Konstanz bald leer?*"
)
try:
    st.page_link("views/fragen.py", label="Zum Assistenten", icon="💬")
except Exception:
    st.caption("Assistent: Navigation links, Seite Fragen.")

with st.expander("Datenquellen & Stand"):
    st.write(f"Aktive Geräte (melden): **{_de(int(k.get('geraete_live') or 0))}**")
    st.write({
        "Flotten-Verwaltung": "verbunden" if settings.fleetmgmt_mssql_password else "nicht konfiguriert",
        "Service-System (Radix)": "verbunden" if settings.is_radix_configured else "nicht konfiguriert",
        "Wissens-Datenbank (KRAI)": "verbunden" if settings.krai_pg_password else "nicht konfiguriert",
    })
    st.caption("Die Auswertungs-Datenbank ist ein abgeleiteter Cache aus den drei Quellen "
               "(nur lesend) und wird nächtlich aktualisiert.")
