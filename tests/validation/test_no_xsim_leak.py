"""XSIM's on-disk layout must never leak into `packages/` — CORE agents are
required to discover it purely from data (docs/01-FORENSIC-CORE.md §4.6
"Rules for CORE agents"). This test loads the frame magic from ground truth
(`hidden_layout`, written only by `tools/synthdvr`, which QA alone reads)
and fails if it appears anywhere under `packages/`, in hex-text or
byte-literal form. Replaces Q1's placeholder
(`test_corpus_manifest.py::test_no_xsim_leak_placeholder`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES_DIR = REPO_ROOT / "packages"
TRUTH_DIR = REPO_ROOT / "corpus" / "truth"

_XSIM_TRUTH_CANDIDATES = ["xsim_unknown.json", "xsim_format.json"]


def _load_xsim_magic_hex() -> str | None:
    for name in _XSIM_TRUTH_CANDIDATES:
        path = TRUTH_DIR / name
        if not path.exists():
            continue
        doc = json.loads(path.read_text())
        layout = doc.get("hidden_layout")
        if layout and layout.get("magic"):
            return str(layout["magic"])
    return None


def _needles(magic_hex: str) -> tuple[list[bytes], list[str]]:
    """Every hex/byte-literal spelling of the magic that a leaking parser
    might plausibly contain."""
    raw = bytes.fromhex(magic_hex)
    byte_needles = [
        raw,
        "".join(f"\\x{b:02x}" for b in raw).encode("ascii"),  # b'\x5a\xa5\x3c\xc3'
        "".join(f"\\x{b:02X}" for b in raw).encode("ascii"),  # b'\x5A\xA5\x3C\xC3'
        "".join(f"0x{b:02x}, " for b in raw).encode("ascii").rstrip(b", "),  # 0x5a, 0xa5, ...
    ]
    text_needles = [
        magic_hex.lower(),
        magic_hex.upper(),
        " ".join(f"{b:02X}" for b in raw),  # "5A A5 3C C3"
        " ".join(f"{b:02x}" for b in raw),
        "-".join(f"{b:02x}" for b in raw),
    ]
    return byte_needles, text_needles


def test_no_xsim_leak_in_packages() -> None:
    magic_hex = _load_xsim_magic_hex()
    if magic_hex is None:
        pytest.skip("no xsim truth file generated yet — run `just corpus` first")
    if not PACKAGES_DIR.exists():
        pytest.skip("packages/ does not exist yet")

    byte_needles, text_needles = _needles(magic_hex)
    text_needles = [n for n in text_needles if n]

    hits: list[str] = []
    for path in PACKAGES_DIR.rglob("*"):
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue

        hit_needle: str | None = None
        for bn in byte_needles:
            if bn in data:
                hit_needle = f"byte-literal {bn!r}"
                break
        if hit_needle is None:
            text = data.decode("utf-8", errors="ignore")
            for tn in text_needles:
                if tn in text:
                    hit_needle = f"hex-text {tn!r}"
                    break

        if hit_needle is not None:
            hits.append(f"{path.relative_to(REPO_ROOT)}: {hit_needle}")

    assert hits == [], (
        "XSIM's magic must never appear under packages/ "
        "(docs/01-FORENSIC-CORE.md §4.6):\n" + "\n".join(hits)
    )
