"""Scenario knobs shared by every writer (docs/05-INFRA-QA.md §4.2).

Concrete per-image plans live in each `writers/*.py` module (they need
format-specific control over block/record layout); this module holds only
what's common: the default channel list, the reference "true" clock, a
deterministic seed derivation, and ISO-8601 formatting for ground truth.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

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


# docs/05-INFRA-QA.md §4.2: seizure default "device +5 min 12 s" ahead of
# reference/true time.
SEIZURE_DEVICE_OFFSET_S = 5 * 60 + 12

# docs/05-INFRA-QA.md §4.2: "per-channel OSD drift (default channel 2 =
# +37 s relative to device clock)".
DEFAULT_OSD_DRIFT_S: dict[int, float] = {2: 37.0}


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
