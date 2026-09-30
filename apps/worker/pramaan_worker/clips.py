"""Fallback clip builder: assemble an Annex-B elementary stream from carved
or indexed frames and remux it with ``ffmpeg -c copy`` (CLAUDE.md rule 3:
never re-encode original video; docs/01-FORENSIC-CORE.md §4.7's documented
fallback since PyAV is not installed in this environment).

``pramaan_recovery.clip.build_clips`` (task C2) is the real clip builder
and is preferred when available (see
``pramaan_worker.registry.get_clip_builder``); this module is what
``pramaan_worker.stages.clips`` falls back to otherwise — used only if
``pramaan_recovery`` itself cannot be imported (e.g. a broken/incomplete
install), not in the normal C2-landed case.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pramaan_core.evidence import EvidenceReader
from pramaan_core.models import FrameRef

_FFMPEG_TIMEOUT_S = 60


def build_clip_ffmpeg(
    reader: EvidenceReader, frames: list[FrameRef], out_path: Path, *, fps: float = 12.5
) -> None:
    """Write ``out_path`` (an MP4) from ``frames`` (already sorted by
    ``payload_offset``), stream-copying every NAL byte read straight from
    the evidence image via ``reader.read`` — no frame is ever decoded or
    re-encoded, only demuxed/remuxed.

    Each ``FrameRef.payload_offset``/``payload_len`` already spans its own
    Annex-B start code(s) (a vendor parser or carver's "payload" is the
    access unit's raw elementary-stream bytes, docs/01-FORENSIC-CORE.md
    §4.6/§4.7 — see e.g. ``pramaan_formats.hiksim``'s ``iter_frames`` or
    ``pramaan_recovery.carve.to_frame_refs``), so frames are concatenated
    as-is with no start code re-added.
    """
    if not frames:
        raise ValueError("build_clip_ffmpeg requires at least one frame")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".h264.tmp")
    with tmp.open("wb") as fh:
        for frame in frames:
            fh.write(reader.read(frame.payload_offset, frame.payload_len))
    try:
        # `-fflags +bitexact -flags +bitexact -map_metadata -1` keep the
        # container's non-stream-copied atoms (creation time, encoder tag)
        # out of the output as far as this ffmpeg build allows, in service
        # of CLAUDE.md rule 5 (determinism) — the copied NAL bytes
        # themselves are always byte-identical given the same input.
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-fflags",
                "+genpts+bitexact",
                "-flags",
                "+bitexact",
                "-r",
                str(fps),
                "-f",
                "h264",
                "-i",
                str(tmp),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                "-map_metadata",
                "-1",
                str(out_path),
            ],
            check=True,
            capture_output=True,
            timeout=_FFMPEG_TIMEOUT_S,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", "replace") if exc.stderr else ""
        raise RuntimeError(f"ffmpeg stream-copy remux failed: {stderr}") from exc
    finally:
        tmp.unlink(missing_ok=True)
