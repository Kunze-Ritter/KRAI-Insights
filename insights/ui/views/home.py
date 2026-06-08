"""Übersicht — Wert-Board: die wichtigsten Punkte zum Handeln auf einen Blick."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from insights.core.config import get_settings
from insights.core.db import insights_engine
from insights.ui.freshness import data_stand, render_status_detail
from insights.ui.links import doc
from insights.ui.theme import bar, render_chart, setup_page
from sqlalchemy import text

settings = get_settings()


@st.cache_data(ttl=300)
def frame(sql: str) -> pd.DataFrame:
    with insights_engine().connect() as conn:
        return pd.DataFrame(conn.execute(text(sql)).mappings().all())


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


setup_page("📊 KRAI Insights",
           "Was die Daten gerade hergeben — die wichtigsten Punkte zum Handeln. "
           "Für konkrete Fragen den Assistenten (Seite Fragen) nutzen.")
st.caption(f"📖 Wie die Zahlen entstehen und warum: [Dokumentation]({doc('README.md')}) "
           f"· [Datenquellen & Datenschutz]({doc('datenquellen.md')})")

k = lagebericht()
if not k:
    st.info("Kennzahlen derzeit nicht verfügbar — bitte Datenbank-Verbindung prüfen.")
    st.stop()

claims = int(k.get("garantie_claims") or 0)
claims_serial = int(k.get("garantie_claims_serial") or 0)
claims_toner = int(k.get("garantie_claims_toner") or 0)
preis = int(k.get("toner_preis_median") or 0)
restwert = float(k.get("claim_restwert_summe") or 0)
schaetz = round(restwert * preis)

# --- Hero: Geld zurückholen (Garantie) -------------------------------------
st.subheader("💰 Geld zurückholen — Garantie")
c1, c2, c3 = st.columns(3)
c1.metric("Geschätztes Rückhol-Potenzial (Toner)", _eur(schaetz),
          help=f"Nur TONER ({_de(claims_toner)} Fälle): erstattet wird die nicht verbrauchte Restlaufzeit "
               f"(Summe der Restanteile {_de(restwert)}) x ~{preis} € mittlerer Tonerpreis. Ersatzteile "
               "haben andere Preise und sind hier NICHT enthalten (separat unter Ersatzteile). "
               f"Grobe Schätzung. Methodik: {doc('garantie.md', '4-was-ist-der--wert-restwert-modell')}")
c2.metric("Reklamierbare Garantiefälle", _de(claims),
          help="Material innerhalb 1 Jahr UND unter 70 % der Soll-Laufleistung; Fehlmeldungen "
               "(Wiedereinsetzen / Tür auf-zu) sind herausgerechnet.")
c3.metric("davon serial-belegt", _de(claims_serial),
          help="Mit Hersteller-Seriennummer = stärkster Nachweis. Manche Hersteller (z. B. Konica "
               "Minolta, Kyocera) melden keine Seriennummer — diese Fälle sind über die FleetMgmt-Zähler "
               "belegt, aber ohne Serial.")
st.caption(
    f"Die Garantiefälle erreichten im Schnitt nur **{int(k.get('claim_schnitt_pct') or 0)} %** der "
    "Hersteller-Soll-Laufleistung. Erstattet wird nur der **ungenutzte Anteil** (z. B. 30 % erreicht → "
    f"70 % erstattbar). **{_de(claims_serial)}** Fälle sind serial-belegt (starker Nachweis), der Rest über "
    f"die Zähler belegt. Zusätzlich **{_de(int(k.get('verhandlung_kandidaten') or 0))}** Verhandlungs-"
    "Kandidaten (über 1 Jahr, aber unter Soll). Liste: Seite Verbrauchsmaterial → Garantie-Bewertung."
)
_niedrig = int(k.get("garantie_claims_niedrig") or 0)
if _niedrig:
    st.caption(
        "Die Headline zählt nur Fälle mit **belastbarem** Hersteller-Soll (Konfidenz hoch/mittel). "
        f"Weitere **{_de(_niedrig)}** mögliche Fälle haben eine unsichere OEM-Referenz (Modell mit vielen "
        "Toner-Varianten / breiter Reichweiten-Spanne) — separat unter Verbrauchsmaterial → "
        "Garantie-Bewertung (Konfidenz niedrig) zum manuellen Prüfen."
    )
st.markdown(f"**Wichtig:** Die Summe ist historisch (~9 Jahre); heute einreichbar ist nur das jüngste "
            f"Zeitfenster. Methodik, Restwert-Modell und Zeitfenster: [Doku Garantie]({doc('garantie.md')}).")

with st.expander("💡 Woher die Ersparnis kommt — nach Material"):
    mat = frame("SELECT material, art, garantiefaelle, restwert_summe, verhandlung "
                "FROM insights.vw_warranty_by_material")
    if not mat.empty:
        mat["geschaetzt_eur"] = (
            pd.to_numeric(mat["restwert_summe"], errors="coerce").fillna(0) * preis
        ).round().astype(int)
        render_chart(bar(
            mat, x="geschaetzt_eur", y="material", color="art", top=15,
            labels={"geschaetzt_eur": "geschätzt € (Toner-Basis)", "material": "Material"},
            title="Rückhol-Potenzial nach Material (€, Toner-Basis)",
        ))
        mat = mat.rename(columns={
            "material": "Material", "art": "Art", "garantiefaelle": "Garantiefälle",
            "restwert_summe": "Restwert-Summe", "verhandlung": "Verhandlung",
            "geschaetzt_eur": "geschätzt € (Toner-Basis)",
        })
        st.dataframe(mat, width="stretch", hide_index=True)
        st.caption("Der €-Wert basiert auf dem mittleren Tonerpreis — für Toner belastbar, bei Teilen "
                   "(kein Toner) nur grobe Orientierung (echte Teilepreise fehlen). Teil-kein-Toner = "
                   "CRU-Teile wie Resttonerbehälter, Fixiereinheit, Transfer — keine farblosen Toner.")

st.divider()

# --- Service & Datenqualität ------------------------------------------------
st.subheader("🛠️ Service & Datenqualität")
s1, s2, s3, s4, s5 = st.columns(5)
s1.metric("Ersatzteil-Frühausfälle", _de(int(k.get("ersatzteil_fruehausfaelle") or 0)),
          help="Ersatzteile, die zu früh ausfielen (unter Hersteller-Soll bzw. innerhalb 1 Jahr erneut "
               "getauscht) → Reklamation/Geld zurück. Seite: Ersatzteile & Standzeit.")
s2.metric("Still & unter Vertrag", _de(int(k.get("stille_unter_vertrag") or 0)),
          help="Geräte unter Vertrag, die keine Zähler mehr melden → Abrechnung läuft auf Schätzwerten. "
               "Seite: Datenqualität → Abrechnungs-Risiko.")
s3.metric("Kundenzuordnung prüfen", _de(int(k.get("kunden_abweichung") or 0)),
          help="Gerät hat in FleetMgmt und Radix verschiedene Kunden → Toner-Fehlversand-Risiko. "
               "Seite: Datenqualität → Kunden-Abgleich.")
s4.metric("Verbrauch in 14 Tagen fällig", _de(int(k.get("verbrauch_14d") or 0)),
          help="Toner/Teile, die bald leer sind → Liefer-/Tourenplanung. Seite: Verbrauchsmaterial.")
s5.metric("Auffällige Geräte", _de(int(k.get("problem_geraete") or 0)),
          help="Sehr viele Alarme (defekte Sensoren / wiederkehrende Störungen). Seite: Service-Qualität.")
st.caption(f"📖 Methodik: [Datenqualität & Abgleich]({doc('datenqualitaet.md')}) · "
           f"[Ersatzteile/Garantie]({doc('garantie.md', '6-ersatzteile-nicht-nur-toner')}) · "
           f"[Kennzahlen-Glossar]({doc('kennzahlen.md')})")

_cov = frame("SELECT count(*) FILTER (WHERE ueber_klickpreis_6pct) n "
             "FROM insights.vw_coverage_by_customer")
if not _cov.empty and int(_cov.iloc[0]["n"] or 0) > 0:
    st.markdown(f"📈 **{int(_cov.iloc[0]['n'])} Kunden** drucken über **6 %** Deckung (Klickpreis-Annahme) → "
                "mehr Tonerverbrauch als berechnet. Seite **Deckung & Kalkulation** (Nachberechnung + "
                "Entwickler-Risiko bei hoher Deckung).")

with st.expander("🔄 Falschzuordnungen / Datenfehler zum Korrigieren"):
    mm = frame(
        "SELECT 'Kundenzuordnung FleetMgmt vs Radix' AS art, count(*) n "
        "FROM insights.vw_customer_device_mismatch WHERE abgleich='abweichung' "
        "UNION ALL SELECT 'Toner woanders eingebaut', count(*) "
        "FROM insights.vw_material_install_check WHERE einbau_status='woanders_eingebaut' "
        "UNION ALL SELECT 'Teilewechsel Fake-Verdacht', count(*) "
        "FROM insights.vw_vbm_validation WHERE validierung='verdacht_fake'"
    )
    if not mm.empty:
        render_chart(bar(
            mm, x="n", y="art",
            labels={"n": "Anzahl", "art": "Art der Abweichung"},
            title="Daten-Korrekturen nach Art",
        ))
        st.dataframe(mm.rename(columns={"art": "Art der Abweichung", "n": "Anzahl"}),
                     width="stretch", hide_index=True)
    st.caption("Details + Listen: Seite **Datenqualität & Abgleich** (Kunden-Abgleich, Material-Einbau, "
               "Teilewechsel-Validierung). Beispiele — abweichende Kundenzuordnung:")
    bsp = frame(
        "SELECT device_serial AS seriennummer, radix_device_number AS radix_id, "
        "fleet_kunde AS kunde_fleet, radix_kunde AS kunde_radix, "
        "subnetz_passt_zu AS ip_beleg FROM insights.vw_customer_device_mismatch "
        "WHERE abgleich='abweichung' AND subnetz_passt_zu IN ('fleet','radix') LIMIT 10"
    )
    if not bsp.empty:
        st.dataframe(bsp, width="stretch", hide_index=True)

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

_stand = data_stand()
if _stand:
    st.caption(f"🕒 Daten-Stand: **{_stand}** (jüngster Stand über alle Kerntabellen).")

with st.expander("Datenquellen & Stand"):
    st.write(f"Aktive Geräte (melden): **{_de(int(k.get('geraete_live') or 0))}**")
    st.write({
        "Flotten-Verwaltung": "verbunden" if settings.fleetmgmt_mssql_password else "nicht konfiguriert",
        "Service-System (Radix)": "verbunden" if settings.is_radix_configured else "nicht konfiguriert",
        "Wissens-Datenbank (KRAI)": "verbunden" if settings.krai_pg_password else "nicht konfiguriert",
    })
    st.caption("Die Auswertungs-Datenbank ist ein abgeleiteter Cache aus den drei Quellen "
               "(nur lesend) und wird nächtlich aktualisiert.")
    st.divider()
    st.caption("Aktualität je Tabelle und letzter nächtlicher Lauf:")
    render_status_detail()
