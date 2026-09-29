"""Writes `corpus/manifest.json` (docs/05-INFRA-QA.md §4.3): one entry per
generated image with its config and SHA-256. Purely a tracking/index file
(not itself a hashed derived artefact under CLAUDE.md rule 5) — its
`generated_at` timestamp is informational only and is never part of what
determinism tests compare.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pramaan_synthdvr.scenario import iso


def write_manifest(
    manifest_path: Path,
    profile: str,
    entries: list[dict[str, Any]],
    *,
    generated_at_s: float,
) -> None:
    doc = {
        "profile": profile,
        "generated_at": iso(generated_at_s),
        "images": sorted(entries, key=lambda e: e["name"]),
        "note": (
            "Written by `just corpus` (tools/synthdvr, docs/05-INFRA-QA.md §4). "
            "Images live in corpus/images/ (gitignored); ground truth lives in "
            "corpus/truth/<image>.json + <image>.frames.parquet (frames.parquet "
            "is gitignored too — it's regenerable from the same config)."
        ),
    }
    manifest_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


def image_entry(name: str, family: str, scenario: str, path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "name": name,
        "family": family,
        "scenario": scenario,
        "path": f"corpus/images/{path.name}",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }
