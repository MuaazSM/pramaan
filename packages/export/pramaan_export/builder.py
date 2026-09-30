"""High-level signed-export orchestration (docs/02-BACKEND.md §10)."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pramaan_core.evidence import EvidenceReader
from pramaan_core.models import FrameRef
from pramaan_custody.keys import sign as ed25519_sign

from pramaan_export.boxes import MANIFEST_BOX_UUID, SIGNATURE_BOX_UUID, append_uuid_boxes
from pramaan_export.manifest import (
    build_export_manifest,
    export_id,
    manifest_bytes,
    manifest_sha256,
)
from pramaan_export.mux import build_elementary_stream, estimate_fps, remux_stream_copy


class NoFramesToExport(ValueError):
    """Raised when the requested recording/channel/time range matches no frames."""


@dataclass(frozen=True)
class ExportResult:
    export_id: str
    manifest: dict[str, Any]
    manifest_sha256: str
    video_sha256: str
    signature_b64: str
    mp4_path: Path
    signature_path: Path
    manifest_path: Path


def _frame_sort_key(f: FrameRef) -> tuple[int, int]:
    ts = f.ts_header_us if f.ts_header_us is not None else -1
    return (ts, f.payload_offset)


def build_export(
    reader: EvidenceReader,
    *,
    source_image_id: str,
    source_sha256: str,
    channel: int | None,
    recording_id: str | None,
    frames: list[FrameRef],
    from_norm_us: int | None,
    to_norm_us: int | None,
    examiner_username: str,
    examiner_role: str,
    signing_key: Ed25519PrivateKey,
    out_dir: Path,
    tool_version: str,
    leading_sps_pps: bytes | None = None,
) -> ExportResult:
    """Build a signed, stream-copied MP4 export from ``frames`` (already
    selected and ordered by the caller: either every frame of one recording,
    or every frame of one channel within a time window — see
    ``apps/api/pramaan_api/real/export_store.py``).
    """
    if not frames:
        raise NoFramesToExport("No frames match the requested recording/channel/time range.")

    ordered = sorted(frames, key=_frame_sort_key)
    stream = build_elementary_stream(reader, ordered, leading_sps_pps=leading_sps_pps)
    fps = estimate_fps(ordered)

    frame_ids = [f.frame_id for f in ordered]
    byte_ranges = [{"offset": f.payload_offset, "length": f.payload_len} for f in ordered]
    device_ts = [f.ts_header_us for f in ordered if f.ts_header_us is not None]
    device_start = min(device_ts) if device_ts else None
    device_end = max(device_ts) if device_ts else None

    # Build to a content-addressed temp name first (ffmpeg needs a real
    # path), then compute video_sha256 from the muxed bytes before appending
    # any box — the box payload depends on this hash, so mux must come first.
    tmp_path = out_dir / "_tmp_export.mp4"
    remux_stream_copy(stream, fps, tmp_path)
    base_mp4 = tmp_path.read_bytes()
    video_sha256 = hashlib.sha256(base_mp4).hexdigest()

    manifest = build_export_manifest(
        source_image_id=source_image_id,
        source_sha256=source_sha256,
        channel=channel,
        recording_id=recording_id,
        frame_ids=frame_ids,
        byte_ranges=byte_ranges,
        device_start_us=device_start,
        device_end_us=device_end,
        from_norm_us=from_norm_us,
        to_norm_us=to_norm_us,
        examiner={"username": examiner_username, "role": examiner_role},
        video_sha256=video_sha256,
        tool_version=tool_version,
    )
    m_bytes = manifest_bytes(manifest)
    m_sha256 = manifest_sha256(manifest)
    signature_b64 = ed25519_sign(signing_key, m_bytes)
    xid = export_id(m_sha256)

    final_bytes = append_uuid_boxes(
        base_mp4,
        [
            (MANIFEST_BOX_UUID, m_bytes),
            (SIGNATURE_BOX_UUID, signature_b64.encode("ascii")),
        ],
    )

    mp4_path = out_dir / f"{xid}.mp4"
    mp4_path.write_bytes(final_bytes)
    tmp_path.unlink(missing_ok=True)

    signature_path = out_dir / f"{xid}.mp4.sig"
    signature_path.write_text(signature_b64, encoding="ascii")
    manifest_path = out_dir / f"{xid}.manifest.json"
    manifest_path.write_bytes(m_bytes)

    return ExportResult(
        export_id=xid,
        manifest=manifest,
        manifest_sha256=m_sha256,
        video_sha256=video_sha256,
        signature_b64=signature_b64,
        mp4_path=mp4_path,
        signature_path=signature_path,
        manifest_path=manifest_path,
    )


def signature_b64_to_bytes(signature_b64: str) -> bytes:
    return base64.b64decode(signature_b64)
