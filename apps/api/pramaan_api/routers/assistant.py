"""Claude assistant (AI-owned from Wave 2 — docs/02-BACKEND.md §2, §4;
docs/03-AI-TIMELINE.md §8).

Thin, self-contained typed stub (see the module docstring in
``routers/timeline.py`` for the pattern every AI-owned router file follows).
Every route 404s when ``LLM_ENABLED=false`` (the Wave 0 default — CLAUDE.md
rule 6: the LLM never produces a finding, and here it is not even wired up
yet), per docs/02-BACKEND.md §4.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from pramaan_api.deps import get_current_user
from pramaan_api.errors import ApiError
from pramaan_api.fixtures import store
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["assistant"])


class EvidenceSearchFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channels: list[int] | None = None
    from_ist: str | None = None
    to_ist: str | None = None
    source: str | None = None
    deleted_only: bool | None = None
    motion_min: float | None = None
    detection_class: str | None = None
    log_kind: str | None = None
    text: str | None = None


class AssistantQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str


class AssistantQueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter: EvidenceSearchFilter
    result_count: int
    results: list[dict[str, Any]]


class ReportFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str


class AssistantDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[ReportFact]


class DraftSentence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    evidence_ids: list[str]


class LlmUsageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    prompt_sha256: str
    response_sha256: str
    created_utc: str


def _require_llm_enabled(settings: Settings) -> None:
    if not settings.llm_enabled:
        raise ApiError(
            404,
            "llm_disabled",
            "The assistant is disabled (LLM_ENABLED=false).",
            {"hint": "set PRAMAAN_LLM_ENABLED=true"},
        )


@router.post("/cases/{cid}/assistant/query", response_model=AssistantQueryResponse)
def assistant_query(
    cid: str,
    body: AssistantQueryRequest,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> AssistantQueryResponse:
    _require_llm_enabled(settings)
    del body  # fixture stub: no NL parsing yet, returns an empty/default filter
    if store.get_case(cid) is None:
        raise ApiError(404, "not_found", f"case '{cid}' was not found.")
    return AssistantQueryResponse(filter=EvidenceSearchFilter(), result_count=0, results=[])


@router.post("/cases/{cid}/assistant/draft", response_model=list[DraftSentence])
def assistant_draft(
    cid: str,
    body: AssistantDraftRequest,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> list[DraftSentence]:
    _require_llm_enabled(settings)
    if store.get_case(cid) is None:
        raise ApiError(404, "not_found", f"case '{cid}' was not found.")
    # Fixture stub: echo one sentence per fact, citing that fact's own id —
    # satisfies the narrative validator's "every sentence cites an evidence
    # id that exists" rule (docs/03-AI-TIMELINE.md §8.3) without calling a
    # model.
    return [DraftSentence(text=fact.text, evidence_ids=[fact.id]) for fact in body.facts]


@router.get("/llm/usage", response_model=list[LlmUsageEntry])
def llm_usage(
    user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> list[LlmUsageEntry]:
    _require_llm_enabled(settings)
    return []
