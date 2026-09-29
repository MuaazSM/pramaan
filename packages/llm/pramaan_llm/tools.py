"""The ``search_evidence`` tool (docs/03-AI-TIMELINE.md §8.3.1).

The model never queries the case database itself — it calls this tool with
structured arguments, the server validates them against
:class:`EvidenceSearchFilter` and executes the query locally (the actual
query implementation lives with whoever owns the case data access layer;
here it's a :class:`SearchExecutor` the caller injects, so this package
never imports from ``apps/api`` — packages/* must not import apps/*,
CLAUDE.md / docs/PRD.md §8). The model only ever sees the filter it built
and, if it asks for one, an aggregate count — never raw result rows unless
the caller chooses to hand them back (docs/03-AI-TIMELINE.md §8.3.1).
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class EvidenceSearchFilter(BaseModel):
    """Arguments the model must supply to ``search_evidence``. Field names
    and semantics match docs/03-AI-TIMELINE.md §8.3.1 exactly, and this is
    the same shape ``apps/api/pramaan_api/routers/assistant.py`` exposes in
    ``AssistantQueryResponse.filter`` — the router imports this class
    instead of redefining it."""

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


SEARCH_EVIDENCE_TOOL: dict[str, Any] = {
    "name": "search_evidence",
    "description": (
        "Search this case's recordings, frames, log events and motion "
        "segments using structured filters. Call this for any question "
        "about times, channels, deletions, motion or log events. Never "
        "guess at case facts — if the filter returns nothing, say the data "
        "isn't there."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "channels": {
                "type": ["array", "null"],
                "items": {"type": "integer"},
                "description": "Channel numbers to restrict the search to.",
            },
            "from_ist": {
                "type": ["string", "null"],
                "description": "Start of the time window, ISO 8601, IST.",
            },
            "to_ist": {
                "type": ["string", "null"],
                "description": "End of the time window, ISO 8601, IST.",
            },
            "source": {
                "type": ["string", "null"],
                "description": "Recording/frame source: 'index', 'carved', or 'inferred'.",
            },
            "deleted_only": {
                "type": ["boolean", "null"],
                "description": "Restrict to recordings/frames flagged as deleted.",
            },
            "motion_min": {
                "type": ["number", "null"],
                "description": "Minimum motion score.",
            },
            "detection_class": {
                "type": ["string", "null"],
                "description": "Detection class: 'person', 'vehicle', 'two_wheeler', 'other'.",
            },
            "log_kind": {
                "type": ["string", "null"],
                "description": "Vendor log event kind, e.g. 'time_change', 'hdd_format'.",
            },
            "text": {
                "type": ["string", "null"],
                "description": "Free-text match against log event descriptions.",
            },
        },
    },
    "cache_control": {"type": "ephemeral"},
}


class SearchExecutor(Protocol):
    """Injected by the caller (the API router) — runs an
    :class:`EvidenceSearchFilter` against the real case data locally and
    returns ``(result_count, results)``. ``results`` must already be
    metadata-only (no frame bytes, no thumbnails) — callers should still run
    it through :func:`pramaan_llm.guard.payload_guard` before handing it
    back to the model for summarisation."""

    def __call__(
        self, case_id: str, filt: EvidenceSearchFilter
    ) -> tuple[int, list[dict[str, Any]]]: ...
