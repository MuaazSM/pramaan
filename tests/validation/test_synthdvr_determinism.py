"""Fast determinism check for the video-encoding primitive every synthdvr
writer relies on (docs/05-INFRA-QA.md §4.1, §4.2 "Deterministic: seeded
RNG; same config → identical image hash"). Encodes a small clip twice and
compares bytes. Deliberately tiny (12 frames) so it stays outside the
`slow` marker and runs in every `just check-qa`.

The heavier, full-image version of this check
(`test_synthdvr_writers.py::test_determinism_same_config_same_hash`) is
marked `slow` since it re-encodes a whole recording twice.
"""

from __future__ import annotations

import hashlib

from pramaan_synthdvr.video import ChannelSpec, ClipSpec, MotionEvent, render_elementary_stream


def test_render_elementary_stream_is_deterministic() -> None:
    channel = ChannelSpec(channel=1, name="Gate", width=320, height=240)
    clip = ClipSpec(
        channel=channel,
        num_frames=12,
        start_epoch_s=1_770_000_000.0,
        seed=42,
        motion_events=[MotionEvent(2, 8)],
    )
    a = render_elementary_stream(clip)
    b = render_elementary_stream(clip)
    assert a == b
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


def test_render_elementary_stream_differs_with_seed() -> None:
    channel = ChannelSpec(channel=1, name="Gate", width=320, height=240)
    base = ClipSpec(
        channel=channel, num_frames=12, start_epoch_s=1_770_000_000.0, seed=1, motion_events=[]
    )
    other = ClipSpec(
        channel=channel, num_frames=12, start_epoch_s=1_770_000_000.0, seed=2, motion_events=[]
    )
    assert render_elementary_stream(base) != render_elementary_stream(other)
