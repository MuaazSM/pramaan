"""Regression test for task FIX-2: HWSIM writer recording-id collision.

``tools/synthdvr/pramaan_synthdvr/writers/hwsim.py``'s ``_Recording.id``
hash used to omit the "format" scenario's generation term
(``sha256(f"{channel}|{round_index}")``). Because the "format" scenario's
post-reset generation 2 restarts ``round_index`` at 0, generation 1's
round 0 and generation 2's (only) round collided on the exact same id for
a given channel — every genuinely-live generation-2 frame was silently
mislabelled ``deleted=True``/``overwritten=True`` in ground truth
(docs/progress/C3.md "Cross-workstream issues": *"every one of
generation-2's real, live, un-deleted frames is mislabelled
`deleted=True`/`overwritten=True`"*). The fix adds ``generation`` to the
id hash (matching HIKSIM's/DHSIM's own ``_Recording.id`` convention, which
both already include it).

This reads the already-generated, checked-in ``corpus/truth/`` files (the
same convention as ``test_corpus_manifest.py`` — cheap, and correct
against whatever a real ``just corpus`` produced) rather than invoking the
writer directly, so it stays outside the ``slow`` marker every writer-build
test in this codebase uses and actually runs under ``just check-qa``'s
default gate, per this task's brief ("used by check-qa").
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TRUTH_DIR = REPO_ROOT / "corpus" / "truth"

_TRUTH_JSON = TRUTH_DIR / "hwsim_format.json"
_TRUTH_PARQUET = TRUTH_DIR / "hwsim_format.frames.parquet"


def _skip_if_missing() -> None:
    if not _TRUTH_JSON.exists() or not _TRUTH_PARQUET.exists():
        pytest.skip(
            "corpus/truth/hwsim_format.{json,frames.parquet} not generated yet — "
            "run `just corpus` first"
        )


def test_hwsim_format_recording_ids_are_unique_per_generation() -> None:
    """No two distinct HWSIM recordings on ``hwsim_format.img`` may share a
    ``recording_id`` — the direct symptom of the collision bug. Grouping
    every frame by ``recording_id``, each group must be internally
    consistent: a single, unambiguous ``deleted`` value (a colliding id
    would merge generation 1's genuinely-deleted frames with generation
    2's genuinely-live frames under one id, producing a group with *both*
    ``deleted=True`` and ``deleted=False`` rows) and a single channel.
    """
    _skip_if_missing()
    pq = pytest.importorskip("pyarrow.parquet")
    frames = pq.read_table(_TRUTH_PARQUET).to_pylist()
    assert frames, "hwsim_format.frames.parquet is empty"

    by_recording: dict[str, list[dict[str, object]]] = defaultdict(list)
    for f in frames:
        by_recording[str(f["recording_id"])].append(f)

    for rec_id, group in by_recording.items():
        deleted_values = {bool(f["deleted"]) for f in group}
        assert len(deleted_values) == 1, (
            f"recording {rec_id} mixes deleted={deleted_values} across its own frames — "
            "a colliding recording id merged two distinct recordings' frames"
        )
        channels = {f["channel"] for f in group}
        assert len(channels) == 1, f"recording {rec_id} mixes channels {channels}"


def test_hwsim_format_generation_2_frames_are_not_marked_deleted() -> None:
    """The exact regression this task fixes: before the fix, *every* frame
    on ``hwsim_format.img`` (all 900, both generations) came back
    ``deleted=True`` — generation 2's genuinely-live frames included. Real
    channel-list-backed HWSIM `format` scenario has 12 recordings (8 in
    generation 1: 2 rounds x 4 channels, all deleted; 4 in generation 2:
    1 round x 4 channels, all live) and 900 frames total (12 x 75).
    """
    _skip_if_missing()
    pq = pytest.importorskip("pyarrow.parquet")
    frames = pq.read_table(_TRUTH_PARQUET).to_pylist()

    recording_ids = {str(f["recording_id"]) for f in frames}
    assert len(recording_ids) == 12, (
        f"expected 12 distinct recordings (8 generation-1 + 4 generation-2), "
        f"got {len(recording_ids)} — a ghost collision would silently reduce this count"
    )

    deleted_count = sum(1 for f in frames if f["deleted"])
    live_count = sum(1 for f in frames if not f["deleted"])
    assert live_count == 300, (
        f"expected 300 live (generation-2) frames, got {live_count} — a recording-id "
        "collision would misreport these as deleted (0 live)"
    )
    assert deleted_count == 600, f"expected 600 deleted (generation-1) frames, got {deleted_count}"

    truth = json.loads(_TRUTH_JSON.read_text())
    live_truth_recordings = [r for r in truth["recordings"] if r["indexed"]]
    assert len(live_truth_recordings) == 4, (
        f"expected 4 indexed (live) recordings in truth['recordings'], "
        f"got {len(live_truth_recordings)}"
    )
    for r in live_truth_recordings:
        assert r["frames"] == 75, r
        assert not r["deleted"], r
