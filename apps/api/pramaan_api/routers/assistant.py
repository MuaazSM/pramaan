"""Claude assistant (AI-owned, task A3 — docs/02-BACKEND.md §2, §4;
docs/03-AI-TIMELINE.md §8).

Wires the real, guarded, budgeted ``pramaan_llm`` layer into the API:

- Provider selection (``PRAMAAN_LLM_PROVIDER=anthropic|local|fixture``, env
  var — deliberately *not* a ``Settings`` field, since ``apps/api``'s other
  files are BACKEND-owned and this task only touches this one file; see
  docs/progress/A3.md "Decisions"). Defaults to ``fixture`` — safe, offline,
  no network — unless explicitly set to ``anthropic``/``local``.
- A per-case SQLite budget ledger (``pramaan_llm.budget.BudgetMeter``,
  backed by ``pramaan_core.db.open_case`` — the real ``llm_calls`` +
  ``audit_log`` schema from ``packages/core/pramaan_core/schema.sql``),
  rooted under a dedicated temp directory rather than ``settings.data_dir``
  so concurrent test runs from other workstreams can never collide with it
  (docs/progress/A3.md "Decisions").
- ``search_evidence`` executed locally against the fixture store's query
  functions (``pramaan_api.fixtures.store`` — the only BACKEND-owned module
  this file reads from, exactly like the W0.3 stub did).

Every route still 404s when ``LLM_ENABLED=false`` (the Wave 0 default),
per docs/02-BACKEND.md §4.

The inference explainer (docs/03-AI-TIMELINE.md §8.3.3,
``pramaan_llm.assistant.explain_inference``) is implemented and tested
(``tests/ai/test_llm_assistant.py``) but deliberately **not** wired to a new
HTTP route here: this file's task (A3) may only touch this one file in
``apps/api``, and ``tests/backend/test_openapi_routes.py`` (BACKEND-owned)
walks every route in ``openapi.json`` generically — a new route needs an
entry in that file's ``_request_bodies``/``_LLM_PATHS`` to pass, which this
task cannot add. See docs/progress/A3.md "Known gaps" for the follow-up.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from datetime import datetime
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

import pramaan_core.db as core_db
from fastapi import APIRouter, Depends
from pramaan_llm.assistant import draft_narrative, run_case_query
from pramaan_llm.budget import BudgetExceededError, BudgetMeter
from pramaan_llm.guard import PayloadGuardViolation
from pramaan_llm.providers.anthropic_provider import AnthropicProvider
from pramaan_llm.providers.fixture_provider import FixtureNotFoundError, FixtureProvider
from pramaan_llm.providers.local_provider import LocalProvider
from pramaan_llm.tools import EvidenceSearchFilter
from pramaan_llm.types import LLMProvider
from pramaan_llm.validator import ReportFact
from pydantic import BaseModel, ConfigDict

from pramaan_api.deps import get_current_user
from pramaan_api.errors import ApiError
from pramaan_api.fixtures import store
from pramaan_api.schemas import Case
from pramaan_api.security import User
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["assistant"])

#: Checked-in canned responses (query/draft/explain scenarios) — see
#: pramaan_llm/providers/fixture_provider.py and this package's "How
#: verified" / API summary notes for how these were recorded. Located via
#: the installed package's own resources rather than a relative-parents
#: path, so it works the same whether pramaan_llm is an editable install or
#: a built wheel.
_BUILTIN_FIXTURES_DIR = Path(str(resources.files("pramaan_llm").joinpath("fixtures")))

#: Budget ledger DBs live under a dedicated temp directory (one per
#: process), never under the shared repo tree — see the module docstring.
_CASE_DB_ROOT = Path(tempfile.gettempdir()) / "pramaan_llm_cases" / f"pid-{os.getpid()}"


# --- request/response models (compatible with the existing openapi.json) ---


class AssistantQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str


class AssistantQueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter: EvidenceSearchFilter
    result_count: int
    results: list[dict[str, Any]]


class AssistantDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[ReportFact]


class DraftSentenceOut(BaseModel):
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


# --- provider / budget wiring ------------------------------------------------


@lru_cache(maxsize=1)
def _select_provider(settings_key: tuple[str | None, str | None]) -> LLMProvider:
    """Cached by the parts of ``Settings`` that affect provider identity, so
    a dependency override in tests (different ``anthropic_api_key``) picks a
    fresh provider instead of reusing a stale cached one."""
    provider_name, api_key = settings_key
    name = (provider_name or "fixture").lower()
    if name == "anthropic":
        return AnthropicProvider(api_key=api_key)
    if name == "local":
        return LocalProvider()
    return FixtureProvider(_BUILTIN_FIXTURES_DIR)


def get_llm_provider(settings: Settings = Depends(get_settings)) -> LLMProvider:
    provider_name = os.environ.get("PRAMAAN_LLM_PROVIDER")
    return _select_provider((provider_name, settings.anthropic_api_key))


def _ensure_case_row(conn: sqlite3.Connection, case: Case) -> None:
    """``llm_calls.case_id`` is a foreign key into ``cases`` (schema.sql).
    This per-case DB is a fresh file the first time the assistant is used
    for a case (see the module docstring — it isn't yet the same DB the
    rest of the fixture-store demo uses), so mirror just enough of the
    case row for that constraint to hold. Real case-row lifecycle belongs
    to whoever wires the real per-case pipeline (a later BACKEND task)."""
    with conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO cases (
                id, case_number, title, fir_number, lab, status, created_utc, updated_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case.id,
                case.case_number,
                case.title,
                case.fir_reference,
                case.lab,
                case.status,
                case.created_utc,
                case.updated_utc,
            ),
        )


@contextlib.contextmanager
def _case_connection(case: Case) -> Iterator[sqlite3.Connection]:
    case_dir = _CASE_DB_ROOT / case.id
    conn = core_db.open_case(case_dir)
    try:
        _ensure_case_row(conn, case)
        yield conn
    finally:
        conn.close()


def _budget_meter(conn: sqlite3.Connection) -> BudgetMeter:
    total_cap = float(os.environ.get("PRAMAAN_LLM_BUDGET_USD_TOTAL", "60.0"))
    case_cap = float(os.environ.get("PRAMAAN_LLM_BUDGET_USD_PER_CASE", "5.0"))
    return BudgetMeter(conn, cap_total_usd=total_cap, cap_case_usd=case_cap)


def _search_evidence(
    case_id: str, filt: EvidenceSearchFilter
) -> tuple[int, list[dict[str, Any]]]:
    """Executes ``search_evidence``'s filter locally against the fixture
    store — the only place this router still reads case data from
    ``pramaan_api.fixtures.store`` (BACKEND-owned; read-only here)."""

    def _parse_us(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            return int(datetime.fromisoformat(value).timestamp() * 1_000_000)
        except ValueError:
            return None

    frm, to = _parse_us(filt.from_ist), _parse_us(filt.to_ist)
    results: list[dict[str, Any]] = []

    if filt.log_kind is not None or filt.text is not None:
        for ev in store.list_log_events(case_id, kind=filt.log_kind):
            if filt.channels and ev.channel not in filt.channels:
                continue
            if filt.text and filt.text.lower() not in ev.kind.lower():
                continue
            results.append(
                {
                    "kind": "log_event",
                    "id": ev.id,
                    "ts_device_us": ev.ts_device_us,
                    "log_kind": ev.kind,
                    "channel": ev.channel,
                    "user": ev.user,
                }
            )

    if filt.detection_class is not None:
        for det in store.list_detections(case_id):
            if det.cls != filt.detection_class:
                continue
            results.append(
                {"kind": "detection", "id": det.id, "cls": det.cls, "score": det.score}
            )

    if filt.motion_min is not None:
        motion_channels: list[int | None] = list(filt.channels) if filt.channels else [None]
        for channel in motion_channels:
            for seg in store.list_motion_segments(case_id, channel=channel):
                if seg.peak_score < filt.motion_min:
                    continue
                results.append(
                    {
                        "kind": "motion",
                        "id": seg.id,
                        "channel": seg.channel,
                        "peak_score": seg.peak_score,
                        "start_norm_us": seg.start_norm_us,
                        "end_norm_us": seg.end_norm_us,
                    }
                )

    if filt.log_kind is None and filt.detection_class is None and filt.motion_min is None:
        deleted = True if filt.deleted_only else None
        recording_channels: list[int | None] = list(filt.channels) if filt.channels else [None]
        for channel in recording_channels:
            for rec in store.list_recordings(
                case_id, channel=channel, source=filt.source, deleted=deleted, frm=frm, to=to
            ):
                results.append(
                    {
                        "kind": "recording",
                        "id": rec.id,
                        "channel": rec.channel,
                        "start_ts_us": rec.start_ts_us,
                        "end_ts_us": rec.end_ts_us,
                        "source": rec.source,
                        "deleted": rec.deleted,
                    }
                )

    return len(results), results


def _to_api_error(exc: Exception) -> ApiError:
    if isinstance(exc, BudgetExceededError):
        return ApiError(
            429,
            "llm_budget_exceeded",
            str(exc),
            {"scope": exc.scope, "spent_usd": exc.spent_usd, "cap_usd": exc.cap_usd},
        )
    if isinstance(exc, PayloadGuardViolation):
        return ApiError(400, "llm_payload_rejected", str(exc), {"path": exc.path})
    if isinstance(exc, FixtureNotFoundError):
        return ApiError(
            503,
            "llm_fixture_missing",
            str(exc),
            {"key": exc.key, "model": exc.model},
        )
    return ApiError(502, "llm_provider_error", str(exc))


# --- routes -----------------------------------------------------------------


@router.post("/cases/{cid}/assistant/query", response_model=AssistantQueryResponse)
def assistant_query(
    cid: str,
    body: AssistantQueryRequest,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    provider: LLMProvider = Depends(get_llm_provider),
) -> AssistantQueryResponse:
    _require_llm_enabled(settings)
    case = store.get_case(cid)
    if case is None:
        raise ApiError(404, "not_found", f"case '{cid}' was not found.")
    try:
        with _case_connection(case) as conn:
            budget = _budget_meter(conn)
            outcome = run_case_query(
                question=body.question,
                case_id=cid,
                provider=provider,
                search_executor=_search_evidence,
                budget=budget,
                actor=user.username,
            )
    except (BudgetExceededError, PayloadGuardViolation, FixtureNotFoundError) as exc:
        raise _to_api_error(exc) from exc
    return AssistantQueryResponse(
        filter=outcome.filter, result_count=outcome.result_count, results=outcome.results
    )


@router.post("/cases/{cid}/assistant/draft", response_model=list[DraftSentenceOut])
def assistant_draft(
    cid: str,
    body: AssistantDraftRequest,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    provider: LLMProvider = Depends(get_llm_provider),
) -> list[DraftSentenceOut]:
    _require_llm_enabled(settings)
    case = store.get_case(cid)
    if case is None:
        raise ApiError(404, "not_found", f"case '{cid}' was not found.")
    try:
        with _case_connection(case) as conn:
            budget = _budget_meter(conn)
            outcome = draft_narrative(
                facts=body.facts, case_id=cid, provider=provider, budget=budget, actor=user.username
            )
    except (BudgetExceededError, PayloadGuardViolation, FixtureNotFoundError) as exc:
        raise _to_api_error(exc) from exc
    return [
        DraftSentenceOut(text=s.text, evidence_ids=s.evidence_ids) for s in outcome.sentences
    ]


@router.get("/llm/usage", response_model=list[LlmUsageEntry])
def llm_usage(
    user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> list[LlmUsageEntry]:
    _require_llm_enabled(settings)
    del user
    if not _CASE_DB_ROOT.exists():
        return []
    entries: list[LlmUsageEntry] = []
    for case_dir in sorted(_CASE_DB_ROOT.iterdir()):
        db_path = case_dir / "case.db"
        if not db_path.exists():
            continue
        conn = sqlite3.connect(str(db_path))
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, model, input_tokens, output_tokens, cost_usd, "
                "request_sha256, response_sha256, created_utc FROM llm_calls "
                "ORDER BY created_utc"
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            entries.append(
                LlmUsageEntry(
                    id=row["id"],
                    model=row["model"],
                    input_tokens=row["input_tokens"],
                    output_tokens=row["output_tokens"],
                    cost_usd=row["cost_usd"],
                    prompt_sha256=row["request_sha256"],
                    response_sha256=row["response_sha256"],
                    created_utc=row["created_utc"],
                )
            )
    return entries
