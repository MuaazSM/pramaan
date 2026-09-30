"""Signed export manifest (docs/02-BACKEND.md §10).

The manifest embedded in the export's ``uuid`` box (and hashed/signed) is
built purely from already-known values — no wall-clock timestamp inside it
(CLAUDE.md rule 5): the export's ``created_utc`` lives only in the caller's
DB row / API response, never inside the bytes that get hashed and signed,
so re-exporting the same frame set twice produces a byte-identical manifest
(and, since the video bytes are also a deterministic stream copy, a
byte-identical signed MP4 modulo nothing at all).
"""

from __future__ import annotations

from typing import Any

from pramaan_core.ids import canonical_json, content_hash, content_id


def build_export_manifest(
    *,
    source_image_id: str,
    source_sha256: str,
    channel: int | None,
    recording_id: str | None,
    frame_ids: list[str],
    byte_ranges: list[dict[str, int]],
    device_start_us: int | None,
    device_end_us: int | None,
    from_norm_us: int | None,
    to_norm_us: int | None,
    examiner: dict[str, str],
    video_sha256: str,
    tool_version: str,
) -> dict[str, Any]:
    return {
        "source_image_id": source_image_id,
        "source_sha256": source_sha256,
        "channel": channel,
        "recording_id": recording_id,
        "frame_ids": sorted(frame_ids),
        "byte_ranges": sorted(byte_ranges, key=lambda r: (r["offset"], r["length"])),
        "device_time_range_us": {"start": device_start_us, "end": device_end_us},
        "normalised_time_range_us": {"from": from_norm_us, "to": to_norm_us},
        "examiner": dict(sorted(examiner.items())),
        "video_sha256": video_sha256,
        "tool": {"name": "pramaan", "version": tool_version, "step": "export.build_export"},
        "export_format_note": (
            "ONVIF-style signed export (not conformance-tested against "
            "ONVIF-ExportFileFormat-Spec) — see docs/02-BACKEND.md §10."
        ),
    }


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return canonical_json(manifest)


def manifest_sha256(manifest: dict[str, Any]) -> str:
    return content_hash(manifest)


def export_id(sha256: str) -> str:
    return content_id("exp", {"manifest_sha256": sha256})
