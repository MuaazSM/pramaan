"""Stream-copy MP4 mux for exports (docs/02-BACKEND.md §10: "MP4 built by
stream copy"). Deliberately mirrors ``pramaan_recovery.clip``'s ffmpeg
invocation (same flags, same fixed metadata) so an export and a clip built
from the same frames are byte-identical up to the trailing uuid boxes this
package appends — CLAUDE.md rule 3 (never re-encode) and rule 5
(determinism) apply equally here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pramaan_core.evidence import EvidenceReader
from pramaan_core.models import FrameRef
from pramaan_formats import nalutil

_FIXED_CREATION_TIME = "1970-01-01T00:00:00.000000Z"
FALLBACK_FPS = 12.5


class ExportMuxError(RuntimeError):
    """``ffmpeg`` failed to remux an export."""


def _leading_sps_pps(payload: bytes) -> bytes | None:
    out = bytearray()
    found = False
    for nal_type, nal_bytes in nalutil.find_nals(payload):
        if nal_type in (nalutil.NAL_SPS, nalutil.NAL_PPS):
            out += b"\x00\x00\x00\x01" + nal_bytes
            found = True
        else:
            break
    return bytes(out) if found else None


def estimate_fps(frames: list[FrameRef]) -> float:
    with_ts = [f for f in frames if f.ts_header_us is not None]
    if len(with_ts) >= 2:
        span_us = with_ts[-1].ts_header_us - with_ts[0].ts_header_us  # type: ignore[operator]
        steps = len(with_ts) - 1
        if span_us > 0:
            return steps * 1_000_000 / span_us
    return FALLBACK_FPS


def build_elementary_stream(
    reader: EvidenceReader, frames: list[FrameRef], *, leading_sps_pps: bytes | None = None
) -> bytes:
    """Concatenate ``frames``' raw Annex-B payloads (already-ordered by the
    caller) into one elementary stream, prepending ``leading_sps_pps`` only
    if the first frame doesn't already lead with its own SPS/PPS."""
    parts: list[bytes] = []
    payloads = [reader.read(f.payload_offset, f.payload_len) for f in frames]
    if payloads and _leading_sps_pps(payloads[0]) is None and leading_sps_pps:
        parts.append(leading_sps_pps)
    parts.extend(payloads)
    return b"".join(parts)


def remux_stream_copy(stream: bytes, fps: float, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-loglevel",
        "error",
        "-fflags",
        "+bitexact",
        "-r",
        f"{fps:.6f}",
        "-f",
        "h264",
        "-i",
        "pipe:0",
        "-c",
        "copy",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-movflags",
        "+faststart",
        "-metadata",
        f"creation_time={_FIXED_CREATION_TIME}",
        "-f",
        "mp4",
        str(out_path),
    ]
    proc = subprocess.run(cmd, input=stream, capture_output=True)
    if proc.returncode != 0:
        raise ExportMuxError(
            f"ffmpeg remux failed (exit {proc.returncode}) writing {out_path}: "
            f"{proc.stderr.decode(errors='replace')}"
        )
