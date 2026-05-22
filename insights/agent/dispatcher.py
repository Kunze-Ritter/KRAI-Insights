"""
Chat dispatcher: maps a German question to one route via Ollama tool-calling,
then runs the deterministic route SQL. The LLM only chooses the route + params;
the answer comes from the route (no hallucinated numbers).
"""

from __future__ import annotations

from insights.agent import routes, text_to_sql
from insights.agent.ollama_client import OllamaClient
from insights.agent.routes import AnswerCard
from insights.core.config import get_settings
from insights.core.logging import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "Du bist ein Analytics-Assistent für Drucksysteme, Verbrauchsmaterial, Garantie, "
    "Service-Kosten und Verträge. Wähle für jede Frage GENAU EINE passende Funktion (Tool) "
    "und fülle deren Parameter aus den Angaben der Frage. Erfinde keine Werte und keine "
    "Zahlen — nutze ausschließlich die Funktionen. Wenn keine Funktion passt, antworte kurz, "
    "dass dazu keine Auswertung verfügbar ist."
)


async def answer(question: str) -> AnswerCard:
    """Route a question through Ollama and return the matching route's AnswerCard."""
    settings = get_settings()
    client = OllamaClient(settings.ollama_base_url, settings.ollama_model)
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

    calls = message.get("tool_calls") or []
    if calls:
        fn = calls[0].get("function", {})
        name = fn.get("name")
        args = fn.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        route = routes.BY_NAME.get(name)
        if route:
            logger.info("routed to %s(%s)", name, args)
            card = route.handler(args)
            card.citation = {**card.citation, "route": name, "parameter": args}
            return card

    # No catalog route matched — try the guarded free-text SQL fallback.
    card = await text_to_sql.generate_and_run(question, client)
    if card is not None:
        return card

    # Last resort — the model's free-text reply with low trust.
    return AnswerCard(
        text=message.get("content") or "Dazu ist keine Auswertung verfügbar.",
        citation={"route": None, "vertrauen": 0.3},
    )
