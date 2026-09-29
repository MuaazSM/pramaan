"""Fixture provider — replays recorded responses, offline (docs/03-AI-TIMELINE.md
§8.1: "used by all tests and CI"; default when ``ANTHROPIC_API_KEY`` isn't set).

Fixtures are content-addressed JSON files, one per *scenario*: the key is
derived from the parts of a request that are fixed per feature — ``model``,
``system`` prompt, and the set of tool names offered — deliberately
**excluding** the free-text ``messages`` content. A case-query fixture
therefore replays the same canned ``search_evidence`` call no matter what
the examiner actually typed; that's a known limitation of a stub/demo
provider (see docs/progress/A3.md "Decisions"), not an attempt to fake a
real model's judgement.

A missing fixture raises :class:`FixtureNotFoundError` naming the exact key
and the file it expected, so recording a new one is a matter of writing that
file (see :func:`request_key` and :func:`write_fixture`), not guessing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pramaan_llm.types import LLMResult, ToolCall


def request_key(
    *,
    model: str,
    system: str,
    tools: list[dict[str, Any]] | None,
) -> str:
    """Deterministic 16-hex-char key for the fixed (non-free-text) parts of
    a request. See the module docstring for why ``messages`` is excluded."""
    tool_names = sorted(t.get("name", "") for t in (tools or []))
    basis = json.dumps(
        {"model": model, "system": system, "tools": tool_names},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


@dataclass
class FixtureNotFoundError(Exception):
    key: str
    path: Path
    model: str
    system: str
    tools: tuple[str, ...]

    def __str__(self) -> str:
        return (
            f"no fixture recorded for key '{self.key}' (model={self.model!r}, "
            f"tools={list(self.tools)!r}) — expected {self.path}. "
            "Record one with pramaan_llm.providers.fixture_provider.write_fixture()."
        )


def _result_to_json(result: LLMResult) -> dict[str, Any]:
    return {
        "text": result.text,
        "tool_calls": [
            {"id": c.id, "name": c.name, "input": c.input} for c in result.tool_calls
        ],
        "stop_reason": result.stop_reason,
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cache_read_input_tokens": result.cache_read_input_tokens,
        "cache_creation_input_tokens": result.cache_creation_input_tokens,
    }


def _result_from_json(data: dict[str, Any]) -> LLMResult:
    return LLMResult(
        text=data.get("text", ""),
        tool_calls=tuple(
            ToolCall(id=c["id"], name=c["name"], input=c.get("input", {}))
            for c in data.get("tool_calls", [])
        ),
        stop_reason=data.get("stop_reason", "end_turn"),
        model=data["model"],
        input_tokens=int(data.get("input_tokens", 0)),
        output_tokens=int(data.get("output_tokens", 0)),
        cache_read_input_tokens=int(data.get("cache_read_input_tokens", 0)),
        cache_creation_input_tokens=int(data.get("cache_creation_input_tokens", 0)),
    )


def write_fixture(
    fixtures_dir: Path,
    *,
    model: str,
    system: str,
    tools: list[dict[str, Any]] | None,
    result: LLMResult,
) -> Path:
    """Record ``result`` as the canned response for this scenario. Used to
    build the checked-in fixture set and by tests that need a scenario the
    checked-in set doesn't cover."""
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    key = request_key(model=model, system=system, tools=tools)
    path = fixtures_dir / f"{key}.json"
    path.write_text(
        json.dumps(_result_to_json(result), sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return path


class FixtureProvider:
    name = "fixture"

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = Path(fixtures_dir)

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResult:
        del messages, max_tokens  # deliberately excluded from the key — see module docstring
        key = request_key(model=model, system=system, tools=tools)
        path = self.fixtures_dir / f"{key}.json"
        if not path.exists():
            raise FixtureNotFoundError(
                key=key,
                path=path,
                model=model,
                system=system,
                tools=tuple(sorted(t.get("name", "") for t in (tools or []))),
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        return _result_from_json(data)
