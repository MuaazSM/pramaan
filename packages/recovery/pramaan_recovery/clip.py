"""Clip builder (docs/01-FORENSIC-CORE.md §4.7 step 6):

"Clip builder groups frames per channel into runs where consecutive
timestamps differ ≤ 2 s (configurable), requires a leading keyframe
(prepends cached SPS/PPS for the channel when a run starts with an IDR
lacking them), and remuxes with PyAV stream copy into
``derived/clips/<recording_id>.mp4``, setting PTS from device timestamps.
Never decode or re-encode."

PyAV is not installed in this environment (not on PyPI as a lockfile-free
wheel install here, and the task explicitly allows a fallback) — this
module uses the documented fallback: ``ffmpeg -c copy`` as a subprocess.
Frames are fed to ffmpeg as a raw Annex B elementary stream (already valid
H.264 Annex B — every access unit here already has its own start codes)
demuxed at a constant frame rate derived from the run's own device
timestamps, then remuxed to MP4 with ``-c copy`` (bitstream copy, never
re-encoded). ``-fflags +bitexact``/``-flags:v +bitexact`` on both the input
and output sides keep two runs on the same input byte-identical (no
wall-clock muxer metadata) — CLAUDE.md rule 5.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from pramaan_core.evidence import EvidenceReader
from pramaan_core.ids import content_id
from pramaan_core.models import FrameRef, Provenance
from pramaan_core.provenance import make_provenance
from pramaan_formats import nalutil

#: docs/01-FORENSIC-CORE.md §4.7 step 6: "consecutive timestamps differ ≤ 2 s".
DEFAULT_MAX_GAP_US = 2_000_000

#: Used only when a run has fewer than two timestamped frames to estimate a
#: frame rate from (docs/05-INFRA-QA.md §4.1's corpus is a fixed 12.5 fps;
#: a real image's rate would ideally come from the vendor header instead).
FALLBACK_FPS = 12.5

_FIXED_CREATION_TIME = "1970-01-01T00:00:00.000000Z"


class ClipBuildError(RuntimeError):
    """``ffmpeg`` failed to remux a clip."""


@dataclass(frozen=True)
class ClipResult:
    clip_id: str
    channel: int
    path: Path
    frame_ids: tuple[str, ...]
    start_ts_us: int | None
    end_ts_us: int | None
    fps: float
    provenance: Provenance


def _frame_sort_key(f: FrameRef) -> tuple[int, int]:
    ts = f.ts_header_us if f.ts_header_us is not None else -1
    return (ts, f.payload_offset)


def group_runs(
    frames: list[FrameRef], max_gap_us: int = DEFAULT_MAX_GAP_US
) -> list[list[FrameRef]]:
    """Group ``frames`` (any order, any mix of ``source``) into runs where
    consecutive (timestamp-sorted) frames are no more than ``max_gap_us``
    apart. A missing timestamp on either side of a pair never splits a run
    — offset ordering is trusted for those frames instead."""
    if not frames:
        return []
    ordered = sorted(frames, key=_frame_sort_key)
    runs: list[list[FrameRef]] = [[ordered[0]]]
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        gap_exceeded = (
            prev.ts_header_us is not None
            and cur.ts_header_us is not None
            and (cur.ts_header_us - prev.ts_header_us) > max_gap_us
        )
        if gap_exceeded:
            runs.append([cur])
        else:
            runs[-1].append(cur)
    return runs


def _leading_sps_pps(payload: bytes) -> bytes | None:
    """The Annex B bytes (with 4-byte start codes) of every SPS/PPS NAL at
    the *start* of ``payload``, or ``None`` if it doesn't lead with one."""
    out = bytearray()
    found = False
    for nal_type, nal_bytes in nalutil.find_nals(payload):
        if nal_type in (nalutil.NAL_SPS, nalutil.NAL_PPS):
            out += b"\x00\x00\x00\x01" + nal_bytes
            found = True
        else:
            break
    return bytes(out) if found else None


_PARAM_SET_FRAME_TYPES = ("SPS", "PPS", "SEI", "VPS")


def _coalesce_leading_param_sets(
    run: list[FrameRef], payloads: list[bytes]
) -> list[bytes]:
    """Bundle each maximal run of leading parameter-set frames
    (``frame_type`` ``SPS``/``PPS``/``SEI``/``VPS``) together with the
    *next* frame's payload into one concatenated Annex-B blob — the same
    per-access-unit payload shape HIKSIM/DHSIM already produce for a
    keyframe (their frame payload convention bundles a keyframe's own
    SPS/PPS into one payload span, docs/progress/C2.md).

    HWSIM headers every NAL individually on disk and (FIX-5) emits one
    :class:`FrameRef` per NAL rather than per access unit, so a run's
    leading SPS/PPS/SEI NALs arrive here as their own, separate frames
    instead of embedded in the following keyframe's payload. Coalescing
    them first means the rest of this module (`_leading_sps_pps`'s
    single-payload scan and the ``sps_pps_cache`` update below) only ever
    has to reason about one shape, regardless of which convention produced
    the frames. For HIKSIM/DHSIM (which never emit ``SPS``/``PPS``/``SEI``
    frame types — their own parameter sets, when present, are already
    embedded inside an ``I`` frame's own payload bytes) this is a no-op:
    each input payload maps to exactly one, unchanged output entry, so a
    non-video "other"-typed frame (e.g. DHSIM's audio records) is never
    merged with anything either."""
    out: list[bytes] = []
    pending = bytearray()
    for frame, payload in zip(run, payloads, strict=True):
        if frame.frame_type in _PARAM_SET_FRAME_TYPES:
            pending += payload
            continue
        if pending:
            payload = bytes(pending) + payload
            pending = bytearray()
        out.append(payload)
    if pending:
        # An orphan trailing parameter-set frame with no following frame to
        # attach to (shouldn't occur — every access-unit grouper in this
        # codebase always ends a group on a VCL NAL) — keep it rather than
        # silently drop bytes.
        out.append(bytes(pending))
    return out


def _estimate_fps(run: list[FrameRef]) -> float:
    with_ts = [f for f in run if f.ts_header_us is not None]
    if len(with_ts) >= 2:
        span_us = with_ts[-1].ts_header_us - with_ts[0].ts_header_us  # type: ignore[operator]
        steps = len(with_ts) - 1
        if span_us > 0:
            return steps * 1_000_000 / span_us
    return FALLBACK_FPS


def _remux_stream_copy(stream: bytes, fps: float, out_path: Path) -> None:
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
        raise ClipBuildError(
            f"ffmpeg remux failed (exit {proc.returncode}) writing {out_path}: "
            f"{proc.stderr.decode(errors='replace')}"
        )


def build_clips(
    reader: EvidenceReader,
    image_id: str,
    channel: int,
    frames: list[FrameRef],
    out_dir: Path,
    *,
    sps_pps_cache: dict[int, bytes] | None = None,
    max_gap_us: int = DEFAULT_MAX_GAP_US,
    parent_sha256: str | None = None,
) -> list[ClipResult]:
    """Build one playable MP4 per run of ``frames`` belonging to ``channel``
    (docs/01-FORENSIC-CORE.md §4.7 step 6). ``sps_pps_cache`` is shared
    across calls for the same image so a later channel/run can reuse an
    earlier run's SPS/PPS if it starts on an IDR that itself lacks them
    (e.g. a carved fragment beginning mid-GOP). Evidence bytes are read
    only through ``reader`` (CLAUDE.md rule 1/2); every clip's byte content
    depends only on the frames given, never on wall-clock time — running
    this twice on the same input produces byte-identical MP4s."""
    if sps_pps_cache is None:
        sps_pps_cache = {}
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[ClipResult] = []
    for run in group_runs(frames, max_gap_us=max_gap_us):
        payloads = [reader.read(f.payload_offset, f.payload_len) for f in run]
        coalesced = _coalesce_leading_param_sets(run, payloads)

        stream_parts: list[bytes] = []
        if _leading_sps_pps(coalesced[0]) is None:
            cached = sps_pps_cache.get(channel)
            if cached is not None:
                stream_parts.append(cached)
        for payload in coalesced:
            stream_parts.append(payload)
            sps_pps = _leading_sps_pps(payload)
            if sps_pps is not None:
                sps_pps_cache[channel] = sps_pps
        stream = b"".join(stream_parts)

        fps = _estimate_fps(run)
        start_ts = run[0].ts_header_us
        end_ts = run[-1].ts_header_us
        frame_ids = tuple(sorted(f.frame_id for f in run))
        clip_id = content_id(
            "clip", {"image_id": image_id, "channel": channel, "frame_ids": frame_ids}
        )
        clip_path = out_dir / f"{clip_id}.mp4"
        _remux_stream_copy(stream, fps, clip_path)

        provenance = make_provenance(
            step="recovery.build_clip",
            params={
                "image_id": image_id,
                "channel": channel,
                "frame_count": len(run),
                "fps": round(fps, 6),
                "max_gap_us": max_gap_us,
                "frame_ids": list(frame_ids),
            },
            parent_sha256=parent_sha256,
        )
        _write_provenance_sidecar(clip_path, provenance)

        results.append(
            ClipResult(
                clip_id=clip_id,
                channel=channel,
                path=clip_path,
                frame_ids=tuple(f.frame_id for f in run),
                start_ts_us=start_ts,
                end_ts_us=end_ts,
                fps=fps,
                provenance=provenance,
            )
        )
    return results


def _write_provenance_sidecar(clip_path: Path, provenance: Provenance) -> None:
    """``<clip_path>.provenance.json`` — same convention as
    ``pramaan_core.acquire``'s ``<dest_path>.provenance.json`` sidecar
    (docs/progress/W0.2.md "Decisions"), since ``clips`` isn't a file the
    ``Provenance`` model itself can be embedded into (it's an MP4)."""
    from pramaan_core.ids import canonical_json

    sidecar = clip_path.with_suffix(clip_path.suffix + ".provenance.json")
    sidecar.write_bytes(canonical_json(provenance.model_dump()))
