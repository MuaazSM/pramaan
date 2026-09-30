"""FIX-3: frame ids must be unique per physical frame, not per payload.

docs/progress/QD.md found that (pre-FIX-3) ``FrameRef.frame_id`` was a pure
hash of the payload bytes, so two distinct physical frames that happen to
carry identical bytes — e.g. a repeated/carved duplicate, or a static scene
carved twice from different offsets — collapsed onto the same id. This
exercises the real production code path (``pramaan_recovery.carve``, the
generic carver every other vendor carver's own frame-construction mirrors)
end to end, rather than only the ``pramaan_core.ids.frame_id`` helper in
isolation (see ``tests/core/test_ids.py`` for the unit-level coverage).
"""

from __future__ import annotations

from pathlib import Path

from pramaan_core.evidence import EvidenceReader
from pramaan_recovery.carve import CarvedAccessUnit, to_frame_refs

IMAGE_ID = "img_" + "a" * 16


def _write_duplicate_payload_image(path: Path, payload: bytes) -> tuple[int, int]:
    """A tiny raw file with the same ``payload`` bytes written twice, at two
    different offsets. Returns (offset_a, offset_b)."""
    gap = b"\x00" * 64
    offset_a = 0
    offset_b = len(payload) + len(gap)
    path.write_bytes(payload + gap + payload)
    return offset_a, offset_b


def test_duplicate_payload_frames_at_different_offsets_get_different_ids(
    tmp_path: Path,
) -> None:
    payload = b"\x00\x00\x00\x01A" + b"\xab" * 250  # arbitrary fixed-size "frame"
    image_path = tmp_path / "dup.raw"
    offset_a, offset_b = _write_duplicate_payload_image(image_path, payload)

    aus = [
        CarvedAccessUnit(
            payload_offset=offset_a, payload_len=len(payload), codec="h264", is_idr=True, sps=None
        ),
        CarvedAccessUnit(
            payload_offset=offset_b, payload_len=len(payload), codec="h264", is_idr=True, sps=None
        ),
    ]

    with EvidenceReader.open(str(image_path)) as r:
        frames = to_frame_refs(r, IMAGE_ID, aus, channels=[1, 1])

    assert len(frames) == 2
    frame_a, frame_b = frames
    # Same payload bytes, so the same content, but two different physical
    # locations on disk — the id must reflect that.
    assert frame_a.payload_sha256 == frame_b.payload_sha256
    assert frame_a.frame_id != frame_b.frame_id
    # payload_sha256 is still the pure, un-salted integrity hash of the bytes.
    import hashlib

    assert frame_a.payload_sha256 == hashlib.sha256(payload).hexdigest()


def test_frame_id_is_deterministic_across_two_carve_runs(tmp_path: Path) -> None:
    payload = b"\x00\x00\x00\x01A" + b"\xcd" * 250
    image_path = tmp_path / "det.raw"
    offset_a, _offset_b = _write_duplicate_payload_image(image_path, payload)

    au = [
        CarvedAccessUnit(
            payload_offset=offset_a, payload_len=len(payload), codec="h264", is_idr=True, sps=None
        )
    ]

    with EvidenceReader.open(str(image_path)) as r:
        frames_run1 = to_frame_refs(r, IMAGE_ID, list(au), channels=[1])
    with EvidenceReader.open(str(image_path)) as r:
        frames_run2 = to_frame_refs(r, IMAGE_ID, list(au), channels=[1])

    assert frames_run1[0].frame_id == frames_run2[0].frame_id
    assert frames_run1[0].payload_sha256 == frames_run2[0].payload_sha256
