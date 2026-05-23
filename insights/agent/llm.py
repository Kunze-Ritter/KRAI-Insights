"""
LLM backends for the agent: local Ollama or OpenRouter (OpenAI-compatible).

Both clients expose the same async ``chat(messages, tools=None)`` that returns a
normalized assistant message dict::

    {"role": str, "content": str,
     "tool_calls": [{"function": {"name": str, "arguments": dict}}]}

so the dispatcher and the text-to-SQL fallback stay backend-agnostic. OpenRouter
returns OpenAI-shaped responses (``choices[0].message``, tool-call ``arguments`` as a
JSON string) — we reshape them to the Ollama shape (arguments already a dict).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp

from insights.agent.ollama_client import OllamaClient
from insights.core.config import Settings
from insights.core.logging import get_logger

logger = get_logger(__name__)


class OpenRouterClient:
    """Calls OpenRouter's OpenAI-compatible /chat/completions (tool-calling capable)."""

    # transient statuses worth a short retry (free models are often briefly 429ed upstream)
    _RETRYABLE = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_s: int = 120,
        max_retries: int = 1,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.max_retries = max_retries

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Return the assistant message dict, normalized to the Ollama shape."""
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # OpenRouter uses these for attribution / free-tier routing (optional).
            "HTTP-Referer": "https://github.com/Kunze-Ritter/KRAI-Insights",
            "X-Title": "krai-insights",
        }
        url = f"{self.base_url}/chat/completions"
        timeout = aiohttp.ClientTimeout(total=self.timeout_s)
        status, body = 0, ""
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(self.max_retries + 1):
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status < 400:
                        return self._normalize(await resp.json())
                    status, body = resp.status, (await resp.text())[:200]
                logger.warning("OpenRouter %s (attempt %d/%d): %s",
                               status, attempt + 1, self.max_retries + 1, body[:160])
                if status in self._RETRYABLE and attempt < self.max_retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                break
        raise ValueError(f"OpenRouter HTTP {status}: {body}")

    @staticmethod
    def _normalize(data: dict[str, Any]) -> dict[str, Any]:
        """Reshape an OpenAI response into the Ollama-style message dict."""
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls: list[dict[str, Any]] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append({"function": {"name": fn.get("name"), "arguments": args or {}}})
        return {
            "role": msg.get("role", "assistant"),
            "content": msg.get("content") or "",
            "tool_calls": calls,
        }

    async def ping(self) -> bool:
        """True if OpenRouter is reachable with this key."""
        timeout = aiohttp.ClientTimeout(total=8)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{self.base_url}/models", headers=headers) as resp:
                return resp.status == 200


class FallbackLLMClient:
    """Try the primary backend; on any error fall back to the secondary.

    Used so OpenRouter (better model) is preferred but the agent stays up via local
    Ollama when a free model is rate-limited (429) or otherwise unavailable.
    """

    def __init__(self, primary: Any, fallback: Any) -> None:
        self.primary = primary
        self.fallback = fallback

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        try:
            return await self.primary.chat(messages, tools)
        except Exception as exc:
            logger.warning(
                "primary LLM (%s) failed: %s — falling back to %s",
                type(self.primary).__name__, exc, type(self.fallback).__name__,
            )
            return await self.fallback.chat(messages, tools)

    async def ping(self) -> bool:
        try:
            return await self.primary.ping()
        except Exception:
            return await self.fallback.ping()


def get_llm_client(settings: Settings) -> OllamaClient | OpenRouterClient | FallbackLLMClient:
    """Return the configured LLM client.

    OpenRouter (with an automatic Ollama fallback) when ``llm_provider=openrouter`` AND
    a key is set; otherwise plain Ollama (also the safe path if openrouter is selected
    without a key).
    """
    if settings.llm_provider.lower() == "openrouter":
        if settings.openrouter_api_key:
            logger.info(
                "LLM backend: OpenRouter (%s) with Ollama fallback", settings.openrouter_model
            )
            primary = OpenRouterClient(
                settings.openrouter_api_key,
                settings.openrouter_model,
                settings.openrouter_base_url,
            )
            fallback = OllamaClient(settings.ollama_base_url, settings.ollama_model)
            return FallbackLLMClient(primary, fallback)
        logger.warning(
            "LLM_PROVIDER=openrouter but OPENROUTER_API_KEY is empty — falling back to Ollama"
        )
    logger.info("LLM backend: Ollama (%s)", settings.ollama_model)
    return OllamaClient(settings.ollama_base_url, settings.ollama_model)
