"""
Angemeldeter Nutzer aus Cloudflare Access.

Cloudflare Access reicht nach dem SSO-Login Header an die App durch:
  - ``Cf-Access-Authenticated-User-Email`` — die E-Mail des Nutzers
  - ``Cf-Access-Jwt-Assertion`` — signiertes JWT (für stärkere Prüfung; hier nicht nötig,
    da die App nur über den Tunnel erreichbar ist, nicht direkt).

Lokal (ohne Cloudflare davor) sind die Header nicht da -> current_user() == None.
Die Rollen-Funktion ist bewusst simpel gehalten als Haken für später.
"""

from __future__ import annotations

import streamlit as st

_EMAIL_HEADER = "Cf-Access-Authenticated-User-Email"


def current_user() -> str | None:
    """E-Mail des per Cloudflare Access angemeldeten Nutzers, oder None (lokal/ohne SSO)."""
    try:
        headers = st.context.headers or {}
    except Exception:
        return None
    # st.context.headers ist case-insensitiv, zur Sicherheit beide Schreibweisen prüfen.
    email = headers.get(_EMAIL_HEADER) or headers.get(_EMAIL_HEADER.lower())
    return email.strip() if email else None


def logout_url() -> str:
    """Relativer Cloudflare-Access-Logout-Pfad (gleiche Domain)."""
    return "/cdn-cgi/access/logout"


def render_user_badge() -> None:
    """Zeigt den angemeldeten Nutzer + Abmelden-Link in der Sidebar (nur hinter CF Access)."""
    user = current_user()
    if not user:
        return
    with st.sidebar:
        st.caption(f"👤 Angemeldet als **{user}**  ·  [Abmelden]({logout_url()})")
