"""Optional live smoke test (docs/03-AI-TIMELINE.md §9): one real Haiku
call, only if both ``ANTHROPIC_API_KEY`` and ``LLM_LIVE_SMOKE=1`` are set in
the environment. Neither is set tonight — this test must skip, never run,
in the offline gate (``just check`` / CI).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live

_HAS_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))
_LIVE_SMOKE = os.environ.get("LLM_LIVE_SMOKE") == "1"


@pytest.mark.skipif(
    not (_HAS_KEY and _LIVE_SMOKE),
    reason="live smoke requires ANTHROPIC_API_KEY and LLM_LIVE_SMOKE=1 (not set)",
)
def test_one_live_haiku_call_logs_cost() -> None:
    from pramaan_llm.config import MODEL_CHEAP
    from pramaan_llm.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider()
    result = provider.complete(
        model=MODEL_CHEAP,
        system="Reply with exactly the word 'pong'.",
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=16,
    )
    assert result.output_tokens > 0
    print(  # noqa: T201 - deliberate: this is the "cost logged" acceptance evidence
        f"live smoke: model={result.model} input_tokens={result.input_tokens} "
        f"output_tokens={result.output_tokens}"
    )
