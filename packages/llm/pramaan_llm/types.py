"""Provider-agnostic request/response shapes (docs/03-AI-TIMELINE.md §8.1).

Every provider (:mod:`pramaan_llm.providers.anthropic_provider`,
``local_provider``, ``fixture_provider``) implements :class:`LLMProvider` and
returns :class:`LLMResult`. Nothing above this module (guards, budget meter,
the assistant orchestration in :mod:`pramaan_llm.assistant`) ever imports a
provider-specific type, so swapping providers is a config change, not a code
change (PRD §7: "swap in a local model with no code changes").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    """One ``tool_use`` block from a model response."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class LLMResult:
    """The normalised result of one :meth:`LLMProvider.complete` call."""

    text: str
    tool_calls: tuple[ToolCall, ...]
    stop_reason: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class LLMProvider(Protocol):
    """docs/03-AI-TIMELINE.md §8.1's ``LLMProvider`` interface.

    ``name`` identifies the provider for budget/audit rows (``"anthropic"``,
    ``"local"``, ``"fixture"``).
    """

    name: str

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResult: ...


@dataclass(frozen=True)
class Message:
    """Convenience constructor for a ``messages[]`` entry (role + text)."""

    role: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}


def user_message(text: str) -> dict[str, Any]:
    return Message(role="user", content=text).to_dict()
