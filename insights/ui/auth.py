"""
Schlankes Passwort-Gate fuers Dashboard (v1 vor Mitarbeiter-Rollout).

Ein gemeinsames Passwort aus `.env` (`DASHBOARD_PASSWORD`). Ist es leer, bleibt das
Dashboard offen (Dev/Docker-Netz) — so gibt es im Entwicklungsbetrieb keinen Lockout.
Ist es gesetzt, verlangt Streamlit das Passwort einmal pro Session.

Bewusst minimal: KEINE Benutzerverwaltung, KEINE Rollen. Das langfristige Ziel ist
Einzel-Anmeldung ueber Microsoft 365 / Entra ID (SSO) — dieses Gate ist die
Zwischenloesung, um das Dashboard vor dem Ausrollen aus dem offenen Netz zu halten.
"""

from __future__ import annotations

import hmac

import streamlit as st

from insights.core.config import get_settings

_AUTH_FLAG = "_auth_ok"


def require_password() -> None:
    """Blockt die Seite, bis das korrekte Passwort eingegeben wurde.

    No-op, wenn kein `dashboard_password` konfiguriert ist (offenes Dev-Setup).
    """
    expected = (get_settings().dashboard_password or "").strip()
    if not expected:
        return  # kein Passwort gesetzt -> offen (Dev)

    if st.session_state.get(_AUTH_FLAG):
        return

    st.title("🔒 KRAI Insights")
    st.caption("Bitte das Dashboard-Passwort eingeben.")
    pw = st.text_input("Passwort", type="password", key="_auth_pw")
    if pw:
        # konstante Laufzeit gegen Timing-Angriffe
        if hmac.compare_digest(pw, expected):
            st.session_state[_AUTH_FLAG] = True
            # Klartext-Passwort nicht in der Session behalten
            st.session_state.pop("_auth_pw", None)
            st.rerun()
        else:
            st.error("Falsches Passwort.")
    st.stop()
