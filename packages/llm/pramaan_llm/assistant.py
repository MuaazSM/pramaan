"""Assistant orchestration (docs/03-AI-TIMELINE.md §8.3): case query,
narrative draft, inference explainer.

Every function here follows the same shape: build a guarded payload, run the
pre-flight budget check, call the provider, record the actual spend, and
return a structured, labelled result. None of these functions import
anything from ``apps/api`` — the case-data access (``search_evidence``'s
execution, the case id, the current actor) is always injected by the caller
(the API router), per ``packages/*`` never importing ``apps/*``
(docs/PRD.md §8).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pramaan_core.ids import content_hash

from pramaan_llm.budget import BudgetMeter, estimate_cost_usd
from pramaan_llm.config import MODEL_CHEAP, MODEL_DRAFT
from pramaan_llm.guard import payload_guard
from pramaan_llm.prompts import load_prompt
from pramaan_llm.tools import SEARCH_EVIDENCE_TOOL, EvidenceSearchFilter, SearchExecutor
from pramaan_llm.types import LLMProvider, LLMResult, user_message
from pramaan_llm.validator import DraftSentence as _RawDraftSentence
from pramaan_llm.validator import ReportFact, ValidationResult, validate_sentences


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _request_hash(*, model: str, system: str, messages: list[dict[str, Any]]) -> str:
    return content_hash({"model": model, "system": system, "messages": messages})


def _response_hash(result: LLMResult) -> str:
    return content_hash(
        {
            "text": result.text,
            "tool_calls": [
                {"id": c.id, "name": c.name, "input": c.input} for c in result.tool_calls
            ],
        }
    )


def _record_call(
    *,
    budget: BudgetMeter,
    case_id: str,
    feature: str,
    provider: LLMProvider,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    result: LLMResult,
    actor: str,
    accepted: bool | None = None,
) -> None:
    budget.record(
        case_id=case_id,
        feature=feature,
        provider=provider.name,
        model=model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cache_read_input_tokens=result.cache_read_input_tokens,
        request_sha256=_request_hash(model=model, system=system, messages=messages),
        response_sha256=_response_hash(result),
        actor=actor,
        now_utc=_now_utc(),
        accepted=accepted,
    )


# --- case query (docs/03-AI-TIMELINE.md §8.3.1) -----------------------------


@dataclass(frozen=True)
class QueryOutcome:
    filter: EvidenceSearchFilter
    result_count: int
    results: list[dict[str, Any]]
    tool_called: bool


def run_case_query(
    *,
    question: str,
    case_id: str,
    provider: LLMProvider,
    search_executor: SearchExecutor,
    budget: BudgetMeter,
    actor: str,
    model: str = MODEL_CHEAP,
    max_tokens: int = 1024,
) -> QueryOutcome:
    """Ask the model to turn ``question`` into a ``search_evidence`` filter,
    then execute that filter locally. Never sends result rows to the model
    (docs/03-AI-TIMELINE.md §8.3.1) — this function's caller decides whether
    to summarise results in a later turn; that is out of scope here."""
    system = load_prompt("system_query.md")
    payload_guard({"question": question})
    messages = [user_message(question)]

    estimated = estimate_cost_usd(
        model=model, system=system, messages=messages, max_tokens=max_tokens
    )
    budget.check(case_id, estimated)

    result = provider.complete(
        model=model,
        system=system,
        messages=messages,
        tools=[SEARCH_EVIDENCE_TOOL],
        max_tokens=max_tokens,
    )
    _record_call(
        budget=budget,
        case_id=case_id,
        feature="assistant.query",
        provider=provider,
        model=model,
        system=system,
        messages=messages,
        result=result,
        actor=actor,
    )

    tool_call = next((c for c in result.tool_calls if c.name == "search_evidence"), None)
    if tool_call is None:
        return QueryOutcome(
            filter=EvidenceSearchFilter(), result_count=0, results=[], tool_called=False
        )
    filt = EvidenceSearchFilter.model_validate(tool_call.input)
    result_count, results = search_executor(case_id, filt)
    return QueryOutcome(filter=filt, result_count=result_count, results=results, tool_called=True)


# --- narrative draft (docs/03-AI-TIMELINE.md §8.3.2) ------------------------


@dataclass(frozen=True)
class DraftOutcome:
    sentences: list[_RawDraftSentence]
    rejected_count: int
    validation: ValidationResult


def _parse_draft_json(text: str) -> list[_RawDraftSentence]:
    """Parse the model's JSON array response. A malformed response (not
    valid JSON, or not a list) is treated as zero sentences — a validator
    failure, not a crash: the caller always gets a well-formed, possibly
    empty, list of accepted sentences."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    sentences: list[_RawDraftSentence] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            sentences.append(_RawDraftSentence.model_validate(item))
        except ValueError:
            continue
    return sentences


def draft_narrative(
    *,
    facts: list[ReportFact],
    case_id: str,
    provider: LLMProvider,
    budget: BudgetMeter,
    actor: str,
    model: str = MODEL_DRAFT,
    max_tokens: int = 4096,
) -> DraftOutcome:
    """Draft report sentences from ``facts`` and validate every sentence
    before returning it (CLAUDE.md rule 6). Rejected sentences are dropped,
    not "fixed" — see ``pramaan_llm.validator``."""
    system = load_prompt("system_draft.md")
    facts_payload = [{"id": f.id, "text": f.text} for f in facts]
    payload_guard(facts_payload)
    messages = [user_message(json.dumps(facts_payload, sort_keys=True))]

    estimated = estimate_cost_usd(
        model=model, system=system, messages=messages, max_tokens=max_tokens
    )
    budget.check(case_id, estimated)

    result = provider.complete(model=model, system=system, messages=messages, max_tokens=max_tokens)

    raw_sentences = _parse_draft_json(result.text)
    validation = validate_sentences(raw_sentences, facts)

    _record_call(
        budget=budget,
        case_id=case_id,
        feature="assistant.draft",
        provider=provider,
        model=model,
        system=system,
        messages=messages,
        result=result,
        actor=actor,
        accepted=len(validation.rejected) == 0,
    )

    return DraftOutcome(
        sentences=validation.accepted,
        rejected_count=len(validation.rejected),
        validation=validation,
    )


# --- inference explainer (docs/03-AI-TIMELINE.md §8.3.3) --------------------


@dataclass(frozen=True)
class ExplainOutcome:
    explanation: str


def explain_inference(
    *,
    layout_stats: dict[str, Any],
    case_id: str,
    provider: LLMProvider,
    budget: BudgetMeter,
    actor: str,
    model: str = MODEL_DRAFT,
    max_tokens: int = 2048,
) -> ExplainOutcome:
    """Explain an ``InferredLayout``'s field statistics in plain language.
    ``layout_stats`` must already be metadata-only (field names, offsets,
    types, confidence, sample counts) — never raw header bytes from
    casework (docs/03-AI-TIMELINE.md §7)."""
    system = load_prompt("system_explain.md")
    payload_guard(layout_stats)
    messages = [user_message(json.dumps(layout_stats, sort_keys=True, default=str))]

    estimated = estimate_cost_usd(
        model=model, system=system, messages=messages, max_tokens=max_tokens
    )
    budget.check(case_id, estimated)

    result = provider.complete(model=model, system=system, messages=messages, max_tokens=max_tokens)
    _record_call(
        budget=budget,
        case_id=case_id,
        feature="assistant.explain",
        provider=provider,
        model=model,
        system=system,
        messages=messages,
        result=result,
        actor=actor,
    )
    return ExplainOutcome(explanation=result.text)
