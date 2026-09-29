"""Local provider (Ollama over HTTP) — optional, for air-gapped labs
(docs/03-AI-TIMELINE.md §8.1, docs/PRD.md §7: "swap in a local model with
no code changes").

Ollama's ``/api/chat`` endpoint doesn't speak Anthropic-style tool use, so
this provider never returns :class:`pramaan_llm.types.ToolCall`\\ s — a
question that needs ``search_evidence`` simply won't get an answer from a
local model. That's an accepted limitation of the air-gapped fallback, not
a bug: it still lets an examiner draft narratives and get explanations
offline.
"""

from __future__ import annotations

from typing import Any

import httpx

from pramaan_llm.types import LLMResult


class LocalProvider:
    name = "local"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        *,
        http_client: httpx.Client | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = http_client or httpx.Client(timeout=timeout)

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResult:
        del tools  # not supported by Ollama's /api/chat — see module docstring
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        response = self._client.post(f"{self._base_url}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        text = str(data.get("message", {}).get("content", ""))
        return LLMResult(
            text=text,
            tool_calls=(),
            stop_reason="end_turn",
            model=str(data.get("model", model)),
            input_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
        )
