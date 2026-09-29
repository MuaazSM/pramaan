"""Library-level tests for ``pramaan_llm.assistant`` (docs/03-AI-TIMELINE.md
§8.3): case query, narrative draft, and the inference explainer — using the
checked-in :class:`FixtureProvider` scenarios, offline, no network.

The inference explainer has no HTTP route (see
``apps/api/pramaan_api/routers/assistant.py``'s module docstring for why);
it's exercised here directly instead.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pramaan_core.db as core_db
import pytest
from pramaan_llm.assistant import draft_narrative, explain_inference, run_case_query
from pramaan_llm.budget import BudgetMeter
from pramaan_llm.config import MODEL_CHEAP, MODEL_DRAFT
from pramaan_llm.providers.fixture_provider import FixtureProvider
from pramaan_llm.tools import EvidenceSearchFilter
from pramaan_llm.validator import ReportFact

_FIXTURES_DIR = (
    Path(__file__).resolve().parents[2] / "packages" / "llm" / "pramaan_llm" / "fixtures"
)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = core_db.open_case(tmp_path / "case_test")
    with connection:
        connection.execute(
            """
            INSERT INTO cases (id, case_number, title, status, created_utc, updated_utc)
            VALUES ('case_1', 'CR-TEST', 'Test case', 'open',
                    '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )
    yield connection
    connection.close()


@pytest.fixture
def budget(conn: sqlite3.Connection) -> BudgetMeter:
    return BudgetMeter(conn)


@pytest.fixture
def provider() -> FixtureProvider:
    return FixtureProvider(_FIXTURES_DIR)


def _fake_search_executor(
    case_id: str, filt: EvidenceSearchFilter
) -> tuple[int, list[dict[str, object]]]:
    del case_id
    results = [{"kind": "recording", "channel": c} for c in (filt.channels or [])]
    return len(results), results


def test_run_case_query_executes_the_models_tool_call(
    provider: FixtureProvider, budget: BudgetMeter
) -> None:
    outcome = run_case_query(
        question="what happened on CH2?",
        case_id="case_1",
        provider=provider,
        search_executor=_fake_search_executor,
        budget=budget,
        actor="examiner",
    )
    assert outcome.tool_called is True
    assert outcome.filter.channels == [2]
    assert outcome.result_count == 1
    assert outcome.results == [{"kind": "recording", "channel": 2}]


def test_run_case_query_records_spend(provider: FixtureProvider, budget: BudgetMeter) -> None:
    assert budget.spent_case_usd("case_1") == 0.0
    run_case_query(
        question="what happened on CH2?",
        case_id="case_1",
        provider=provider,
        search_executor=_fake_search_executor,
        budget=budget,
        actor="examiner",
    )
    assert budget.spent_case_usd("case_1") > 0.0


def test_draft_narrative_validates_and_accepts_a_matching_fact(
    provider: FixtureProvider, budget: BudgetMeter
) -> None:
    facts = [ReportFact(id="fact_1", text="Recording gap on CH2 from 20:00 to 09:00.")]
    outcome = draft_narrative(
        facts=facts, case_id="case_1", provider=provider, budget=budget, actor="examiner"
    )
    assert outcome.rejected_count == 0
    assert len(outcome.sentences) == 1
    assert outcome.sentences[0].evidence_ids == ["fact_1"]


def test_draft_narrative_rejects_when_facts_dont_match_the_citation(
    provider: FixtureProvider, budget: BudgetMeter
) -> None:
    facts = [ReportFact(id="fact_other", text="Unrelated fact.")]
    outcome = draft_narrative(
        facts=facts, case_id="case_1", provider=provider, budget=budget, actor="examiner"
    )
    assert outcome.rejected_count == 1
    assert outcome.sentences == []


def test_explain_inference_returns_plain_language_text(
    provider: FixtureProvider, budget: BudgetMeter
) -> None:
    layout_stats = {
        "header_len": 32,
        "magic": "deadbeef",
        "codec": "h264",
        "confirmed": False,
        "fields": [
            {"name": "timestamp", "offset": 8, "width": 4, "confidence": 0.4, "support": 12}
        ],
    }
    outcome = explain_inference(
        layout_stats=layout_stats,
        case_id="case_1",
        provider=provider,
        budget=budget,
        actor="examiner",
    )
    assert outcome.explanation
    assert "timestamp" in outcome.explanation


def test_calls_use_the_documented_models(
    provider: FixtureProvider, budget: BudgetMeter, conn: sqlite3.Connection
) -> None:
    run_case_query(
        question="q",
        case_id="case_1",
        provider=provider,
        search_executor=_fake_search_executor,
        budget=budget,
        actor="examiner",
    )
    row = conn.execute(
        "SELECT model FROM llm_calls WHERE feature = 'assistant.query'"
    ).fetchone()
    assert row["model"] == MODEL_CHEAP

    draft_narrative(
        facts=[ReportFact(id="fact_1", text="Recording gap on CH2 from 20:00 to 09:00.")],
        case_id="case_1",
        provider=provider,
        budget=budget,
        actor="examiner",
    )
    row = conn.execute("SELECT model FROM llm_calls WHERE feature = 'assistant.draft'").fetchone()
    assert row["model"] == MODEL_DRAFT
