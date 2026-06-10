"""Geräte-Inventar — alle erfassten Drucksysteme mit Status und Zuordnung."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from insights.core.db import insights_engine
from insights.ui.theme import MUTED, POS, WARN, donut, render_chart, setup_page
from sqlalchemy import text

# Technische Status-Werte -> verständliche deutsche Bezeichnung.
STATUS_LABEL = {
    "live": "Aktiv (meldet)",
    "silent": "Still (> 60 Tage)",
    "never_reported": "Nie gemeldet",
    "deactivated": "Deaktiviert",
    "deleted": "Gelöscht",
}
# Spaltennamen der Datenbank -> Anzeige-Überschrift.
SPALTEN = {
    "manufacturer_serial": "Seriennummer",
    "radix_device_number": "Radix-ID",
    "fleetmgmt_device_id": "Fleet-ID",
    "internal_id": "Interne ID",
    "customer_name": "Kunde",
    "customer_city": "Ort",
    "manufacturer_canonical": "Hersteller",
    "model_display": "Modell",
    "hostname": "Hostname",
    "printer_ip": "IP-Adresse",
    "mac_address": "MAC-Adresse",
    "device_status": "Status",
    "telemetry_stale_days": "Tage ohne Meldung",
    "last_data_transfer_at": "Letzte Meldung",
}


@st.cache_data(ttl=300)
def kennzahlen() -> tuple[int, dict[str, int]]:
    with insights_engine().connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM insights.vw_device_lookup")).scalar() or 0
        nach_status = dict(
            conn.execute(
                text("SELECT device_status, count(*) FROM insights.vw_device_lookup GROUP BY device_status")
            ).all()
        )
    return total, nach_status


@st.cache_data(ttl=300)
def geraete(suche: str, status: list[str], limit: int) -> pd.DataFrame:
    clauses = ["1=1"]
    params: dict[str, object] = {}
    if suche:
        clauses.append(
            "AND (manufacturer_serial ILIKE :q OR radix_device_number ILIKE :q "
            "OR customer_name ILIKE :q OR model_display ILIKE :q OR printer_ip ILIKE :q "
            "OR mac_address ILIKE :q OR hostname ILIKE :q OR CAST(fleetmgmt_device_id AS TEXT) = :exact)"
        )
        params["q"] = f"%{suche}%"
        params["exact"] = suche
    if status:
        clauses.append("AND device_status = ANY(:status)")
        params["status"] = status
    params["lim"] = limit
    sql = (
        "SELECT manufacturer_serial, radix_device_number, fleetmgmt_device_id, customer_name, "
        "customer_city, manufacturer_canonical, model_display, hostname, printer_ip, mac_address, "
        "device_status, telemetry_stale_days, "
        "last_data_transfer_at FROM insights.vw_device_lookup "
        f"WHERE {' '.join(clauses)} "
        "ORDER BY (device_status = 'live') DESC, customer_name NULLS LAST LIMIT :lim"
    )
    with insights_engine().connect() as conn:
        df = pd.DataFrame(conn.execute(text(sql), params).mappings().all())
    if not df.empty:
        df["device_status"] = df["device_status"].map(STATUS_LABEL).fillna(df["device_status"])
        df = df.rename(columns=SPALTEN)
    return df


setup_page("🖨️ Geräte-Inventar",
           "Alle erfassten Drucksysteme mit Standort, Kunde, Modell und Meldestatus — "
           "Suche nach Seriennummer, Radix-ID, Kunde, Modell, IP oder Hostname.")

st.caption(
    "**Datenquelle:** FleetMgmt (Flottenverwaltung). Alle Geräte, die jemals von einem "
    "KR-Kunden in FleetMgmt registriert wurden, erscheinen hier.  \n"
    "**Status-Bedeutung:** "
    "🟢 **Aktiv** = hat in den letzten 60 Tagen Zähler gemeldet. "
    "🟡 **Still** = zuletzt vor mehr als 60 Tagen gemeldet (möglicherweise abgebaut oder offline). "
    "⚫ **Nie gemeldet** = wurde eingetragen, hat aber noch nie Daten geschickt. "
    "⚫ **Deaktiviert/Gelöscht** = administrativ inaktiv gesetzt.  \n"
    "**Tipp:** Die Radix-ID in der Tabelle direkt in Radix eingeben, um das Ticket-System zu öffnen."
)

total, nach_status = kennzahlen()
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Geräte gesamt", f"{total:,}".replace(",", "."))
c2.metric("Aktiv (meldet)", f"{nach_status.get('live', 0):,}".replace(",", "."))
c3.metric("Still (> 60 Tage)", f"{nach_status.get('silent', 0):,}".replace(",", "."))
c4.metric("Nie gemeldet", f"{nach_status.get('never_reported', 0):,}".replace(",", "."))
c5.metric("Deaktiviert / Gelöscht",
          f"{nach_status.get('deactivated', 0) + nach_status.get('deleted', 0):,}".replace(",", "."))

_status_colors = {
    "Aktiv (meldet)": POS, "Still (> 60 Tage)": WARN, "Nie gemeldet": MUTED,
    "Deaktiviert": "#71717A", "Gelöscht": "#3F3F46",
}
_status_df = pd.DataFrame(
    [{"status": STATUS_LABEL.get(s, s), "anzahl": int(n)} for s, n in nach_status.items() if n]
)
if not _status_df.empty:
    render_chart(donut(_status_df, names="status", values="anzahl",
                       color_map=_status_colors, title="Flotte nach Meldestatus"))

st.caption(
    "Aktiv bedeutet: das Gerät hat in den letzten 60 Tagen Daten übermittelt. "
    "Still oder nie gemeldet weist auf eine fehlende Verbindung hin "
    "(z. B. ausgebautes Gerät, Netzwerk- oder Software-Problem vor Ort)."
)

st.divider()
st.subheader("Geräteliste")
col_suche, col_status, col_limit = st.columns([3, 2, 1])
suche = col_suche.text_input("Suche — Seriennummer, Radix-ID, Kunde, Modell, Hostname oder IP", "")
status_wahl = col_status.multiselect(
    "Status",
    options=list(STATUS_LABEL.keys()),
    default=["live", "silent", "never_reported"],
    format_func=lambda s: STATUS_LABEL.get(s, s),
)
limit = int(col_limit.number_input("Max. Zeilen", min_value=50, max_value=5000, value=500, step=50))

df = geraete(suche.strip(), status_wahl, limit)
st.write(f"**{len(df):,}**".replace(",", ".") + " Gerät(e) angezeigt")
st.dataframe(df, width="stretch", hide_index=True)

if not df.empty and "Status" in df:
    still = df[df["Status"].isin(["Still (> 60 Tage)", "Nie gemeldet"])]
    if len(still):
        st.warning(
            f"Hinweis: {len(still):,}".replace(",", ".")
            + " der angezeigten Geräte melden derzeit keine Daten. "
            "Für diese Geräte sind Zählerstände nicht aktuell — eine Prüfung vor Ort wird empfohlen."
        )
