"""
KRAI Insights — Streamlit-Einstieg und Navigation.

Startet das Dashboard und bindet die einzelnen Seiten ein. Lokal:
    streamlit run insights/ui/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Projekt-Wurzel in den Pfad legen, damit `insights.*` importierbar ist.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="KRAI Insights", page_icon="📊", layout="wide")

# Konfigurations-Plausibilität einmal je Prozess prüfen (nur Log-Warnungen, nie fatal).
from scripts.env_check import check_env  # noqa: E402


@st.cache_resource
def _env_checked() -> bool:
    return check_env()


_env_checked()

# Authentifizierung läuft am Rand über Cloudflare Access (SSO/Entra ID) — siehe
# docs/deployment.md. Kein App-Passwort-Gate mehr nötig.

# Globaler Daten-Aktualitäts-Banner: zeigt sich NUR bei veralteten Tabellen oder einem
# fehlgeschlagenen Nightly-Lauf (sonst still). Macht "stille Veraltung" sichtbar.
from insights.ui.freshness import render_banner  # noqa: E402

render_banner()

# Angemeldeten Nutzer (Cloudflare Access) in der Sidebar zeigen — no-op lokal/ohne SSO.
from insights.ui.identity import render_user_badge  # noqa: E402

render_user_badge()

# Navigation nach ARBEITSABLAEUFEN/JOBS gruppiert (nicht nach Datenquelle): so liegt
# zusammen, was ein Nutzer fuer EINE Aufgabe braucht. Die Seiten selbst sind unveraendert,
# nur sinnvoll unter Job-Sektionen einsortiert.
pages = {
    "Start": [
        st.Page("views/home.py", title="Übersicht", icon="🏠", default=True),
        st.Page("views/fragen.py", title="Assistent (Fragen)", icon="💬"),
    ],
    "💰 Geld & Chancen": [
        st.Page("views/chancen.py", title="Lizenz & Wettbewerb", icon="💸"),
        st.Page("views/verbrauchsmaterial.py", title="Garantie & Verbrauchsmaterial", icon="🧪"),
        st.Page("views/ersatzteile.py", title="Ersatzteile & Standzeit", icon="🔧"),
    ],
    "🛠️ Service planen": [
        st.Page("views/servicequalitaet.py", title="Service-Qualität", icon="🚨"),
        st.Page("views/service.py", title="Teile-Einsatz & Schulung", icon="🧰"),
    ],
    "💶 Abrechnung & Verträge": [
        st.Page("views/kosten.py", title="Kosten & Verträge", icon="💶"),
        st.Page("views/deckung.py", title="Deckung & Kalkulation", icon="📈"),
    ],
    "🔍 Datenpflege": [
        st.Page("views/datenqualitaet.py", title="Datenqualität & Abgleich", icon="🔍"),
    ],
    "📚 Nachschlagen": [
        st.Page("views/geraeteinventar.py", title="Geräte-Inventar", icon="🖨️"),
    ],
}
st.navigation(pages).run()
