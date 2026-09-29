"""Fixture generation determinism (CLAUDE.md rule 5): re-running
``generate.build()`` must produce byte-identical data — no wall-clock reads,
no unseeded randomness.
"""

from __future__ import annotations

from pramaan_api.fixtures import generate
from pramaan_core.ids import content_hash


def _fingerprint(data: generate.FixtureData) -> str:
    return content_hash(
        {
            "case": data.case.model_dump(mode="json"),
            "recordings": [r.model_dump(mode="json") for r in data.recordings],
            "frames": [f.model_dump(mode="json") for f in data.frames],
            "log_events": [e.model_dump(mode="json") for e in data.log_events],
            "deletion_findings": [d.model_dump(mode="json") for d in data.deletion_findings],
            "clock_models": [c.model_dump(mode="json") for c in data.clock_models],
            "audit_log": [a.model_dump(mode="json") for a in data.audit_log],
        }
    )


def test_build_is_deterministic_across_runs() -> None:
    first = generate.build()
    second = generate.build()
    assert _fingerprint(first) == _fingerprint(second)


def test_build_matches_expected_counts() -> None:
    data = generate.build()
    assert data.case.case_number == "CR-2026-0412"
    assert len(data.channels) == 4
    assert len(data.recordings) == 60
    assert len(data.audit_log) >= 128
    assert len(data.deletion_findings) == 1
    assert any(f.actor == "admin" and f.method == "format" for f in data.deletion_findings)
    assert any(e.kind == "time_change" for e in data.log_events)
    assert len(data.inferred_layouts) == 1
    layout = next(iter(data.inferred_layouts.values()))
    assert layout.confirmed_by is None
