"""Minimal async client for the local Ollama /api/chat endpoint (with tools)."""

from __future__ import annotations

from typing import Any

import aiohttp

from insights.core.logging import get_logger

logger = get_logger(__name__)


class OllamaClient:
    """Calls Ollama /api/chat. Tool-calling capable (model must support tools)."""

    def __init__(self, base_url: str, model: str, timeout_s: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Return the assistant `message` dict (may contain `tool_calls`)."""
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
        url = f"{self.base_url}/api/chat"
        timeout = aiohttp.ClientTimeout(total=self.timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status >= 400:
                    txt = await resp.text()
                    logger.error("Ollama error %s: %s", resp.status, txt[:300])
                    raise ValueError(f"Ollama HTTP {resp.status}: {txt[:200]}")
                data = await resp.json()
        return data.get("message", {})

    async def ping(self) -> bool:
        """True if the Ollama server is reachable."""
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{self.base_url}/api/tags") as resp:
                return resp.status == 200
