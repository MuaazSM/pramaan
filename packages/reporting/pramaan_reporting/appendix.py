"""Appendix hash list (docs/02-BACKEND.md §9 step 2: "appendix with the
full manifest hash list") — every hash value a reader could independently
recompute and cross-check against the manifest, in one place.
"""

from __future__ import annotations

from typing import Any


def build_hash_appendix(manifest: dict[str, Any], report_sha256: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = [
        {"item": "report manifest", "algorithm": "SHA-256", "value": report_sha256}
    ]
    for item in manifest["evidence"]:
        label = item.get("path") or item["id"]
        rows.append({"item": f"evidence: {label}", "algorithm": "SHA-256", "value": item["sha256"]})
        rows.append({"item": f"evidence: {label}", "algorithm": "MD5", "value": item["md5"]})
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
