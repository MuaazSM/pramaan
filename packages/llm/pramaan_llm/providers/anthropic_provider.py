"""Anthropic provider (docs/03-AI-TIMELINE.md §8.1) — the official
``anthropic`` Python SDK, with prompt caching on the system prompt.

``ANTHROPIC_API_KEY`` comes from the environment only (CLAUDE.md): the
constructor never hardcodes or logs a key, and by default (``api_key=None``)
it lets the SDK resolve credentials itself (env var, or an ``ant auth
login`` profile). This provider is never used in tests — offline tests use
:class:`pramaan_llm.providers.fixture_provider.FixtureProvider`; the only
place this class is exercised against the real API is the optional live
smoke test, gated on both ``ANTHROPIC_API_KEY`` and ``LLM_LIVE_SMOKE=1``.
"""

from __future__ import annotations

from typing import Any

import anthropic

from pramaan_llm.types import LLMResult, ToolCall


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self, *, api_key: str | None = None, client: anthropic.Anthropic | None = None
    ) -> None:
        self._client = client or anthropic.Anthropic(api_key=api_key)

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResult:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        response = self._client.messages.create(**kwargs)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, input=dict(block.input or {}))
                )

        usage = response.usage
        return LLMResult(
            text="\n".join(text_parts),
            tool_calls=tuple(tool_calls),
            stop_reason=response.stop_reason or "end_turn",
            model=response.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens or 0,
            cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
        )
