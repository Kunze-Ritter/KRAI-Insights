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

pages = [
    st.Page("views/home.py", title="Übersicht", icon="🏠", default=True),
    st.Page("views/geraeteinventar.py", title="Geräte-Inventar", icon="🖨️"),
    st.Page("views/verbrauchsmaterial.py", title="Verbrauchsmaterial", icon="🧪"),
]
st.navigation(pages).run()
