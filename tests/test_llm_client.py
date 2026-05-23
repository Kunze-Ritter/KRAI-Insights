"""Backend-agnostic LLM client: OpenAI→Ollama response normalization + provider switch."""

from __future__ import annotations

from insights.agent.llm import FallbackLLMClient, OpenRouterClient, get_llm_client
from insights.agent.ollama_client import OllamaClient
from insights.core.config import Settings


def test_openrouter_normalizes_tool_call_with_string_arguments() -> None:
    """OpenAI returns tool-call arguments as a JSON string; we parse them to a dict."""
    raw = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "fehlercode", "arguments": '{"code": "200.03"}'},
                        }
                    ],
                }
            }
        ]
    }
    msg = OpenRouterClient._normalize(raw)
    assert msg["tool_calls"][0]["function"]["name"] == "fehlercode"
    assert msg["tool_calls"][0]["function"]["arguments"] == {"code": "200.03"}


def test_openrouter_normalizes_plain_content() -> None:
    raw = {"choices": [{"message": {"role": "assistant", "content": "Hallo"}}]}
    msg = OpenRouterClient._normalize(raw)
    assert msg["content"] == "Hallo"
    assert msg["tool_calls"] == []


def test_openrouter_handles_malformed_arguments() -> None:
    raw = {
        "choices": [
            {"message": {"tool_calls": [{"function": {"name": "x", "arguments": "{not json"}}]}}
        ]
    }
    msg = OpenRouterClient._normalize(raw)
    assert msg["tool_calls"][0]["function"]["arguments"] == {}


def test_provider_switch_selects_openrouter_when_keyed() -> None:
    s = Settings(llm_provider="openrouter", openrouter_api_key="sk-test", openrouter_model="m")
    client = get_llm_client(s)
    assert isinstance(client, FallbackLLMClient)
    assert isinstance(client.primary, OpenRouterClient)
    assert isinstance(client.fallback, OllamaClient)


def test_provider_falls_back_to_ollama_without_key() -> None:
    s = Settings(llm_provider="openrouter", openrouter_api_key="")
    assert isinstance(get_llm_client(s), OllamaClient)


def test_default_provider_is_ollama() -> None:
    s = Settings(llm_provider="ollama")
    assert isinstance(get_llm_client(s), OllamaClient)
