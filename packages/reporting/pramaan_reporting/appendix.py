"""Appendix hash list (docs/02-BACKEND.md §9 step 2: "appendix with the
full manifest hash list") — every hash value a reader could independently
recompute and cross-check against the manifest, in one place.

The main report body and certificate only ever show the evidence file's
bare name (item 6, docs/progress/FIX-10.md: no absolute host filesystem
path in the rendered document); this appendix is where the full source
path — needed to physically locate the file on the examiner's own
workstation, but meaningless/misleading to a court reader on its own — is
recorded, alongside every hash.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


def _basename(path: str) -> str:
    name = PurePosixPath(str(path).replace("\\", "/")).name
    return name or str(path)


def build_hash_appendix(manifest: dict[str, Any], report_sha256: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = [
        {"item": "report manifest", "algorithm": "SHA-256", "value": report_sha256}
    ]
    for item in manifest["evidence"]:
        path = str(item.get("path") or "")
        label = _basename(path) or item["id"]
        rows.append({"item": f"evidence: {label}", "algorithm": "SHA-256", "value": item["sha256"]})
        rows.append({"item": f"evidence: {label}", "algorithm": "MD5", "value": item["md5"]})
        if path:
            rows.append(
                {"item": f"evidence: {label} — source path", "algorithm": "path", "value": path}
            )
    custody = manifest.get("custody", {})
    if custody.get("head_hash"):
        rows.append(
            {"item": "custody chain head", "algorithm": "SHA-256", "value": custody["head_hash"]}
        )
    for anchor in manifest.get("anchors", []):
        rows.append(
            {
                "item": f"anchor {anchor.get('id', '')} ({anchor.get('backend', '')}, "
                f"seq {anchor.get('from_seq')}-{anchor.get('to_seq')})",
                "algorithm": "SHA-256 (Merkle root)",
                "value": anchor.get("merkle_root", ""),
            }
        )
    for clip in manifest.get("recordings_summary", {}).get("recordings", []):
        rid = clip.get("id")
        if rid:
            rows.append({"item": f"recording {rid}", "algorithm": "content-id", "value": rid})
    return rows
