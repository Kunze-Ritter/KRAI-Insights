"""
Chat dispatcher: maps a German question to one route via Ollama tool-calling,
then runs the deterministic route SQL. The LLM only chooses the route + params;
the answer comes from the route (no hallucinated numbers).
"""

from __future__ import annotations

import json
import re
from typing import Any

from insights.agent import routes, text_to_sql
from insights.agent.llm import get_llm_client
from insights.agent.routes import AnswerCard
from insights.core.config import get_settings
from insights.core.logging import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "Du bist ein Analytics-Assistent für Drucksysteme, Verbrauchsmaterial, Garantie, "
    "Service-Kosten und Verträge. Wähle für jede Frage GENAU EINE passende Funktion (Tool) "
    "und fülle deren Parameter aus den Angaben der Frage. Erfinde keine Werte und keine "
    "Zahlen — nutze ausschließlich die Funktionen. Bei allgemeinen Fragen ('Überblick', "
    "'was ist wichtig', 'wo können wir Geld zurückholen') nutze 'lagebericht'. Wenn keine "
    "Funktion passt, antworte kurz, dass dazu keine Auswertung verfügbar ist."
)

# Second pass: turn the route's (already-correct) data into a short analysis.
ANALYZE_PROMPT = (
    "Du bist Analyst bei einem Druckdienstleister, der Kopierer/Drucksysteme bei Kunden "
    "wartet (Verbrauchsmaterial, Garantie, Service, Verträge). Du bekommst eine Frage, die "
    "bereits korrekt ermittelten FAKTEN (Zahlen mit ihrer Bedeutung und Einheit) und eine "
    "Detailtabelle. Die Fakten sind WAHR und vollständig. Übernimm Zahlen NUR mit exakt der dort "
    "genannten Bedeutung und Einheit — erfinde keine Einheiten, Zeiträume, Abteilungen, Module "
    "oder Produktnamen und rechne nichts um (z. B. eine Anzahl ist KEINE Anzahl Tage). Fasse die "
    "wichtigste Erkenntnis in 2 bis 3 kurzen, sachlichen Sätzen zusammen und gib EINE konkrete "
    "Handlungsempfehlung aus diesem Geschäft (Garantie beim Hersteller einreichen, Kunde "
    "kontaktieren, Daten im System korrigieren, Material/Tour vorbereiten). Wiederhole die "
    "Tabelle nicht."
)


async def _analyze(question: str, card: AnswerCard, client: Any) -> AnswerCard:
    """Append a short LLM analysis of the route's data (data stays the source of truth).

    The model is grounded in the route's already-correct summary text (numbers with their
    meaning) plus the detail table, so it interprets rather than re-deriving figures.
    """
    if card.data is None or card.data.empty:
        return card
    sample = card.data.head(30).to_string(index=False)
    user = (
        f"Frage: {question}\n\n"
        f"Bereits korrekt ermittelte Fakten (Zahlen mit ihrer Bedeutung — nicht verändern):\n{card.text}\n\n"
        f"Detailtabelle ({len(card.data)} Zeilen):\n{sample}"
    )
    try:
        msg = await client.chat([
            {"role": "system", "content": ANALYZE_PROMPT},
            {"role": "user", "content": user},
        ])
    except Exception as exc:
        logger.warning("analysis pass failed: %s", exc)
        return card
    analysis = (msg.get("content") or "").strip()
    if analysis:
        card.text = f"{card.text}\n\n**Auswertung:** {analysis}"
        card.citation = {**card.citation, "analyse": True}
    return card


_EMBEDDED_NAME = re.compile(r'"name"\s*:\s*"([a-z_]+)"')


def _recover_tool_call(content: str) -> tuple[str, dict[str, Any]] | None:
    """Best-effort recover a tool-call the model emitted as TEXT instead of structured.

    Some tool-capable models (observed: qwen2.5:7b via Ollama) occasionally print the
    call into ``content`` — e.g. ``brtc {"name": "abrechnungs_risiko", "arguments":
    {...}}`` — leaving ``tool_calls`` empty. Without this the raw JSON would leak to the
    user. We parse the first JSON object that names a known route and run it normally.
    """
    if not content or "{" not in content:
        return None
    candidate = content[content.find("{"): content.rfind("}") + 1]
    blobs = [candidate]
    m = _EMBEDDED_NAME.search(content)  # fallback: a route name even amid prose
    if m and m.group(1) in routes.BY_NAME:
        blobs.append("{" + m.group(0) + "}")
    for blob in blobs:
        try:
            obj = json.loads(blob)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(obj, dict):
            continue
        name = obj.get("name")
        args = obj.get("arguments", obj.get("parameters", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if name in routes.BY_NAME and isinstance(args, dict):
            return name, args
    return None


async def answer(question: str) -> AnswerCard:
    """Route a question through Ollama and return the matching route's AnswerCard."""
    settings = get_settings()
    client = get_llm_client(settings)
    try:
        message = await client.chat(
            [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}],
            tools=routes.to_ollama_tools(),
        )
    except Exception as exc:
        logger.error("dispatch failed: %s", exc)
        return AnswerCard(
            text=f"Der KI-Dienst ist nicht erreichbar ({exc}). Bitte Ollama-Verbindung prüfen.",
            citation={"route": None, "vertrauen": 0.0},
        )

    name: str | None = None
    args: dict[str, Any] = {}
    calls = message.get("tool_calls") or []
    if calls:
        fn = calls[0].get("function", {})
        name = fn.get("name")
        args = fn.get("arguments") if isinstance(fn.get("arguments"), dict) else {}
    else:
        # The model may have emitted the tool-call as text — recover it before falling back.
        recovered = _recover_tool_call(message.get("content") or "")
        if recovered:
            name, args = recovered
            logger.info("recovered text-emitted tool-call: %s", name)

    route = routes.BY_NAME.get(name) if name else None
    if route:
        logger.info("routed to %s(%s)", name, args)
        card = route.handler(args)
        card.citation = {**card.citation, "route": name, "parameter": args}
        return await _analyze(question, card, client)

    # No catalog route matched — try the guarded free-text SQL fallback.
    card = await text_to_sql.generate_and_run(question, client)
    if card is not None:
        return card

    # Last resort — the model's free-text reply with low trust.
    return AnswerCard(
        text=message.get("content") or "Dazu ist keine Auswertung verfügbar.",
        citation={"route": None, "vertrauen": 0.3},
    )
