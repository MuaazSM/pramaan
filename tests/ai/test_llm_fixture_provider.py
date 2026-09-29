"""FixtureProvider tests (docs/03-AI-TIMELINE.md §8.1/§9: "Full test suite
passes with LLM_PROVIDER=fixture and no network").
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pramaan_llm.providers.fixture_provider import (
    FixtureNotFoundError,
    FixtureProvider,
    request_key,
    write_fixture,
)
from pramaan_llm.types import LLMResult, ToolCall

MODEL = "claude-haiku-4-5-20251001"
SYSTEM = "You are a test system prompt."


def test_request_key_is_deterministic() -> None:
    k1 = request_key(model=MODEL, system=SYSTEM, tools=None)
    k2 = request_key(model=MODEL, system=SYSTEM, tools=None)
    assert k1 == k2
    assert len(k1) == 16


def test_request_key_ignores_message_content(tmp_path: Path) -> None:
    """The fixture cassette is keyed on model+system+tools, not the
    free-text question — see providers/fixture_provider.py's module
    docstring for why."""
    result = LLMResult(
        text="fixed answer",
        tool_calls=(),
        stop_reason="end_turn",
        model=MODEL,
        input_tokens=1,
        output_tokens=1,
    )
    write_fixture(tmp_path, model=MODEL, system=SYSTEM, tools=None, result=result)
    provider = FixtureProvider(tmp_path)

    r1 = provider.complete(model=MODEL, system=SYSTEM, messages=[{"role": "user", "content": "a"}])
    r2 = provider.complete(
        model=MODEL, system=SYSTEM, messages=[{"role": "user", "content": "a completely different question"}]
    )
    assert r1.text == r2.text == "fixed answer"


def test_request_key_changes_with_system_prompt() -> None:
    k1 = request_key(model=MODEL, system="prompt A", tools=None)
    k2 = request_key(model=MODEL, system="prompt B", tools=None)
    assert k1 != k2


def test_request_key_changes_with_tools() -> None:
    k1 = request_key(model=MODEL, system=SYSTEM, tools=None)
    k2 = request_key(model=MODEL, system=SYSTEM, tools=[{"name": "search_evidence"}])
    assert k1 != k2


def test_missing_fixture_raises_typed_error_with_the_expected_key(tmp_path: Path) -> None:
    provider = FixtureProvider(tmp_path)
    expected_key = request_key(model=MODEL, system=SYSTEM, tools=None)
    with pytest.raises(FixtureNotFoundError) as excinfo:
        provider.complete(model=MODEL, system=SYSTEM, messages=[{"role": "user", "content": "x"}])
    assert excinfo.value.key == expected_key
    assert str(expected_key) in str(excinfo.value.path)


def test_round_trips_tool_calls(tmp_path: Path) -> None:
    result = LLMResult(
        text="",
        tool_calls=(ToolCall(id="toolu_1", name="search_evidence", input={"channels": [2]}),),
        stop_reason="tool_use",
        model=MODEL,
        input_tokens=10,
        output_tokens=5,
        cache_read_input_tokens=3,
    )
    write_fixture(
        tmp_path,
        model=MODEL,
        system=SYSTEM,
        tools=[{"name": "search_evidence"}],
        result=result,
    )
    provider = FixtureProvider(tmp_path)
    replayed = provider.complete(
        model=MODEL,
        system=SYSTEM,
        messages=[{"role": "user", "content": "anything"}],
        tools=[{"name": "search_evidence"}],
    )
    assert replayed.stop_reason == "tool_use"
    assert len(replayed.tool_calls) == 1
    assert replayed.tool_calls[0].name == "search_evidence"
    assert replayed.tool_calls[0].input == {"channels": [2]}
    assert replayed.cache_read_input_tokens == 3


def test_builtin_fixtures_directory_has_the_shipped_scenarios() -> None:
    """The router (apps/api/pramaan_api/routers/assistant.py) defaults to
    these — see docs/progress/A3.md "API summary" for how they were
    recorded."""
    fixtures_dir = Path(__file__).resolve().parents[2] / "packages" / "llm" / "pramaan_llm" / "fixtures"
    assert fixtures_dir.is_dir()
    assert list(fixtures_dir.glob("*.json")), "expected at least one checked-in fixture"
