"""Signed export verification (docs/02-BACKEND.md §10:
``POST /exports/verify`` — "accepts a file and returns signature validity,
manifest, and whether the source hashes match a registered evidence
image").

Self-contained: everything needed to verify is embedded in the uploaded MP4
itself (the manifest box and the signature box) — the caller only needs to
supply a way to look up an examiner's public key by username (the signing
identity recorded inside the manifest) and, separately, whether the
manifest's claimed source hash matches a registered evidence image.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pramaan_custody.keys import verify as ed25519_verify

from pramaan_export.boxes import parse_trailing_boxes


@dataclass(frozen=True)
class VerifyOutcome:
    signature_valid: bool
    manifest: dict[str, Any]
    reasons: tuple[str, ...]


def verify_export_bytes(data: bytes, *, pubkey_hex_by_username: dict[str, str]) -> VerifyOutcome:
    """Verify an uploaded export file end to end:

    1. Recover the embedded manifest + detached-style signature from the
       trailing ``uuid`` boxes.
    2. Recompute the video-only SHA-256 (every byte before the first
       Pramaan box) and compare it against the manifest's own claim — this
       is what makes flipping a single byte anywhere in the video stream
       detectable even though the Ed25519 signature itself only covers the
       (small) manifest bytes, not the whole file.
    3. Verify the Ed25519 signature over the manifest bytes, using the
       signing examiner's public key (looked up by the username recorded
       inside the manifest).

    ``signature_valid`` is ``True`` only if every one of the above holds.
    """
    reasons: list[str] = []
    boxes = parse_trailing_boxes(data)

    if boxes.manifest is None:
        return VerifyOutcome(
            signature_valid=False,
            manifest={},
            reasons=("no embedded manifest box found — not a Pramaan signed export",),
        )

    try:
        manifest: dict[str, Any] = json.loads(boxes.manifest)
    except (UnicodeDecodeError, ValueError):
        return VerifyOutcome(
            signature_valid=False, manifest={}, reasons=("embedded manifest is not valid JSON",)
        )

    video_bytes = data[: boxes.video_end_offset]
    recomputed_video_sha256 = hashlib.sha256(video_bytes).hexdigest()
    claimed_video_sha256 = manifest.get("video_sha256")
    if recomputed_video_sha256 != claimed_video_sha256:
        reasons.append(
            "video content hash mismatch — file has been modified since it was "
            f"signed (recomputed {recomputed_video_sha256}, manifest claims "
            f"{claimed_video_sha256})"
        )

    if boxes.signature is None:
        reasons.append("no embedded signature box found")
        sig_ok = False
    else:
        signature_b64 = boxes.signature.decode("ascii", errors="replace")
        examiner_raw = manifest.get("examiner")
        examiner = examiner_raw if isinstance(examiner_raw, dict) else {}
        username = examiner.get("username")
        pubkey_hex = pubkey_hex_by_username.get(username) if username else None
        if pubkey_hex is None:
            reasons.append(f"no known public key for examiner '{username}'")
            sig_ok = False
        else:
            sig_ok = ed25519_verify(pubkey_hex, boxes.manifest, signature_b64)
            if not sig_ok:
                reasons.append("Ed25519 signature over the manifest did not verify")

    signature_valid = sig_ok and recomputed_video_sha256 == claimed_video_sha256
    return VerifyOutcome(signature_valid=signature_valid, manifest=manifest, reasons=tuple(reasons))
