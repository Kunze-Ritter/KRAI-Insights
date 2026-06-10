"""Fragen — Chat-Assistent über die Auswertungsdaten (lokales Ollama)."""

from __future__ import annotations

import asyncio

import streamlit as st
from insights.agent import dispatcher
from insights.agent.ollama_client import OllamaClient
from insights.core.config import get_settings
from insights.ui.theme import setup_page

settings = get_settings()

setup_page(
    "💬 Assistent — Fragen stellen",
    "Stelle eine Frage in normalem Deutsch — der Assistent wählt die passende "
    "Auswertung, rechnet sie und antwortet mit Quellenangabe.",
)


@st.cache_data(ttl=30)
def ollama_erreichbar() -> bool:
    try:
        return asyncio.run(OllamaClient(settings.ollama_base_url, settings.ollama_model).ping())
    except Exception:
        return False


if not ollama_erreichbar():
    st.warning(
        f"KI-Dienst (Ollama) unter {settings.ollama_base_url} ist nicht erreichbar. "
        "Antworten sind erst möglich, sobald die Verbindung steht."
    )

st.info(
    "**Was kann der Assistent?** Fragen in normalem Deutsch stellen — z. B. nach einem "
    "Gerät suchen, Garantiefälle abfragen, Verträge prüfen oder Fehlercodes nachschlagen. "
    "Der Assistent greift auf dieselben Daten wie das Dashboard zu, fasst sie aber als "
    "Text zusammen. Für komplexe Filter und Listen sind die Dashboard-Seiten besser geeignet."
)

beispiele = [
    "Zeig mir Gerät 144052",
    "Toner-Standzeit für bizhub C450i",
    "Welche Garantiefälle gibt es?",
    "Fehlercode 200.03",
    "Welche Verträge laufen bald aus?",
    "Geräte ohne Vertrag",
    "Wie viele Geräte hat Konica Minolta in der Flotte?",
    "Garantie-Übersicht nach Hersteller",
    "Welche Geräte melden nichts mehr?",
]
cols = st.columns(3)
geklickt = ""
for i, b in enumerate(beispiele):
    if cols[i % 3].button(b, width="stretch"):
        geklickt = b

frage = st.text_input("Deine Frage", value=geklickt)
if frage.strip():
    with st.spinner("Suche Antwort …"):
        card = asyncio.run(dispatcher.answer(frage.strip()))
    st.markdown(f"**{card.text}**")
    if card.data is not None and not card.data.empty:
        st.dataframe(card.data, width="stretch", hide_index=True)
    with st.expander("Quelle / Begründung"):
        st.json(card.citation)
