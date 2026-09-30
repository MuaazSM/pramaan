"""Report manifest (docs/02-BACKEND.md §9 step 1).

``build_manifest`` is a pure function over already-gathered, JSON-shaped
input — it never touches a database or the filesystem itself, so the same
inputs always produce the same manifest bytes (CLAUDE.md rule 5) and the
function is trivially unit-testable without any DB/case fixtures. The
*caller* (``apps/api/pramaan_api/real/report_store.py``) is responsible for
reading the case's real state and shaping it into ``ManifestInputs``.

``report_sha256`` is the reproducible "report hash" (PRD §9): the SHA-256 of
the manifest's canonical JSON encoding (``pramaan_core.ids.canonical_json`` —
sorted keys, no whitespace). Nothing wall-clock-derived is inside the
manifest; the generation timestamp belongs in the caller's unhashed
"envelope" alongside the manifest (see ``build_report`` in ``builder.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pramaan_core.ids import canonical_json, content_hash, content_id

#: Always included, honesty-about-synthetic-data limitations (CLAUDE.md
#: rule 7) — additional case-specific limitations are appended after these.
BASE_LIMITATIONS: tuple[str, ...] = (
    "Evidence images in this environment are drawn from a synthetic corpus "
    "modelled on published DVR/NVR layouts. Pramaan has not been validated "
    "against real vendor hardware; do not represent this report as proof of "
    "compatibility with a specific real device without independent testing.",
    "Clock normalisation (multi-clock reconciliation across device, index, "
    "on-screen display and reference time) is produced by a separate AI "
    "timeline workstream; where absent from this report, only the raw clock "
    "observations recorded at evidence intake / from device logs are listed.",
    "Motion analytics and object detections, where produced, are AI drafts "
    "and are never treated as findings on their own — every AI-drafted "
    "sentence in this report is labelled and cites the evidence it was "
    "drafted from, and was explicitly accepted by an examiner before "
    "inclusion.",
    "Anchoring in this report uses the local, hash-chained anchor ledger "
    "only. A permissioned-blockchain (Hyperledger Fabric) anchor backend is "
    "defined but not implemented in this environment; see the custody "
    "section below for which backend produced each anchor listed.",
    "Case data is stored unencrypted at rest in this environment (post-MVP "
    "work item).",
)


@dataclass(frozen=True)
class ManifestInputs:
    case: dict[str, Any]
    examiner: dict[str, Any]
    evidence: list[dict[str, Any]]
    vendor_matches: dict[str, list[dict[str, Any]]]
    recordings: list[dict[str, Any]]
    deletion_findings: list[dict[str, Any]]
    clock_observations: list[dict[str, Any]]
    log_events: list[dict[str, Any]]
    custody: dict[str, Any]
    anchors: list[dict[str, Any]]
    methods: dict[str, Any]
    accepted_ai_drafts: list[dict[str, Any]] = field(default_factory=list)
    extra_limitations: tuple[str, ...] = ()


def _sorted_by_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda d: str(d.get("id", "")))


def build_manifest(inputs: ManifestInputs) -> dict[str, Any]:
    """Build the hashable manifest dict (docs/02-BACKEND.md §9 step 1).

    Every list is sorted by a stable key before inclusion so that two calls
    over logically-identical (but differently-ordered) input produce
    byte-identical canonical JSON — determinism must not depend on a
    database's row order.
    """
    vendor_matches_sorted = {
        image_id: sorted(
            matches, key=lambda m: (-float(m.get("confidence", 0.0)), str(m.get("family", "")))
        )
        for image_id, matches in sorted(inputs.vendor_matches.items())
    }
    return {
        "case": dict(sorted(inputs.case.items())),
        "examiner": dict(sorted(inputs.examiner.items())),
        "evidence": _sorted_by_id(inputs.evidence),
        "vendor_matches": vendor_matches_sorted,
        "methods": dict(sorted(inputs.methods.items())),
        "recordings_summary": {
            "count": len(inputs.recordings),
            "recordings": _sorted_by_id(inputs.recordings),
        },
        "deletion_findings": _sorted_by_id(inputs.deletion_findings),
        "clock_observations": _sorted_by_id(inputs.clock_observations),
        "log_events": _sorted_by_id(inputs.log_events),
        "accepted_ai_drafts": _sorted_by_id(inputs.accepted_ai_drafts),
        "custody": dict(sorted(inputs.custody.items())),
        "anchors": sorted(inputs.anchors, key=lambda a: str(a.get("ts_utc", ""))),
        "limitations": list(BASE_LIMITATIONS) + list(inputs.extra_limitations),
    }


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    """Canonical JSON bytes of ``manifest`` — what's hashed and what's
    written to disk, so re-reading the file and re-hashing it always agree.
    """
    return canonical_json(manifest)


def report_sha256(manifest: dict[str, Any]) -> str:
    return content_hash(manifest)


def report_id(sha256: str) -> str:
    return content_id("rpt", {"report_sha256": sha256})
