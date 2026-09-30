"""Scenario knobs shared by every writer (docs/05-INFRA-QA.md §4.2).

Concrete per-image plans live in each `writers/*.py` module (they need
format-specific control over block/record layout); this module holds only
what's common: the default channel list, the reference "true" clock, a
deterministic seed derivation, and ISO-8601 formatting for ground truth.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from pramaan_synthdvr.video import ChannelSpec

# Reference "true" time T for the whole small corpus (arbitrary, fixed).
TRUE_EPOCH = datetime(2026, 3, 12, 10, 0, 0, tzinfo=UTC)
TRUE_EPOCH_S = TRUE_EPOCH.timestamp()

# docs/05-INFRA-QA.md §4.2: "channels (default 4, names Gate, Shopfront,
# Counter, Rear lane)".
DEFAULT_CHANNEL_NAMES = ["Gate", "Shopfront", "Counter", "Rear lane"]


def default_channels(width: int = 640, height: int = 360) -> list[ChannelSpec]:
    return [
        ChannelSpec(channel=i + 1, name=name, width=width, height=height)
        for i, name in enumerate(DEFAULT_CHANNEL_NAMES)
    ]


# docs/05-INFRA-QA.md §4.2: "per-channel OSD drift (default channel 2 =
# +37 s relative to device clock)".
DEFAULT_OSD_DRIFT_S: dict[int, float] = {2: 37.0}


def seizure_offset_us(clock_segments: list[dict[str, Any]]) -> int:
    """The device clock's offset from true time *at the seizure instant*.

    Physically: DVR displayed time at seizure = true (reference) time at
    seizure + the device's offset at that instant — whatever the last
    (open-ended, ``end_device: null``) clock segment says, since every
    scripted clock event (e.g. ``time_change``) happens strictly before
    the device is seized. Task FIX-6 (docs/VALIDATION.md "Cross-workstream
    issues", Q3 finding): a previous version of this generator applied a
    fixed ``SEIZURE_DEVICE_OFFSET_S = +312 s`` to every image's seizure
    record regardless of what offset was actually baked into that image's
    device timestamps (0 s for every scenario except
    ``hiksim_clockchange``, which bakes in -3600 s after its scripted
    clock-set-back) — so the seizure record disagreed with the disk's own
    clock. This derives the seizure offset from the same ground truth the
    frames themselves are stamped with, so the two can never disagree.
    """
    if not clock_segments:
        return 0
    return int(clock_segments[-1]["offset_true_to_device_us"])


def seed_for(*parts: str) -> int:
    """Deterministic 63-bit seed derived from ``parts`` (e.g. image name +
    channel + recording index) — same config always yields the same seed."""
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") & 0x7FFFFFFFFFFFFFFF


def iso(ts_s: float) -> str:
    """ISO-8601 UTC timestamp (seconds resolution) for ground truth JSON."""
    return datetime.fromtimestamp(ts_s, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def us(ts_s: float) -> int:
    """Microseconds since Unix epoch, rounded — the unit `FrameRef`/truth
    parquet timestamp columns use."""
    return round(ts_s * 1_000_000)
