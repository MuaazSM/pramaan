"""Fingerprinter (docs/01-FORENSIC-CORE.md §4.4).

Loads ``packages/formats/fingerprints.yaml`` (the "DVR genome") and matches
an :class:`~pramaan_core.evidence.EvidenceReader` against every entry,
returning a confidence-ranked list of :class:`~pramaan_core.models.VendorMatch`.

Confidence is the sum of matched signature weights, capped at 1.0. Anything
below 0.3 is a candidate for Tier B inference / Tier C carving rather than a
confirmed Tier A parse (docs/01-FORENSIC-CORE.md §4.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pramaan_core.evidence import EvidenceReader
from pramaan_core.models import VendorMatch

#: Default location of the "DVR genome" — this package's own directory.
DEFAULT_FINGERPRINTS_PATH = Path(__file__).resolve().parent.parent / "fingerprints.yaml"

#: Matches at or above this confidence are treated as a confirmed Tier A/B
#: identification; below it, callers should fall through to inference/carving.
CONFIDENCE_FLOOR = 0.3

#: How much of the image to scan for an `any`-scoped signature; keeps
#: fingerprinting fast even on a large image (data areas are scanned by the
#: vendor parser/carver later, not here).
_ANY_SCOPE_CAP = 64 * 1024 * 1024


@dataclass(frozen=True)
class _Signature:
    literal: bytes
    start: int
    end: int | None
    weight: float


@dataclass(frozen=True)
class _FieldSpec:
    offset: int
    length: int


@dataclass(frozen=True)
class _FamilySpec:
    family: str
    display_name: str
    platform: str | None
    tier: str
    signatures: list[_Signature]
    model_at: _FieldSpec | None
    serial_at: _FieldSpec | None


def _parse_bytes_literal(value: str) -> bytes:
    """YAML string -> raw bytes, decoding any escape sequences (e.g. the
    embedded NUL in DHSIM's magic, written as ``"DHFS4.1\\u0000"``)."""
    return value.encode("utf-8").decode("unicode_escape").encode("latin-1")


def _parse_signature(raw: dict[str, Any]) -> _Signature:
    where = raw["where"]
    start: int
    end: int | None
    if where == "any":
        start, end = 0, _ANY_SCOPE_CAP
    else:
        start = int(where.get("start", 0))
        raw_end = where.get("end")
        end = int(raw_end) if raw_end is not None else None
    return _Signature(
        literal=_parse_bytes_literal(raw["bytes"]),
        start=start,
        end=end,
        weight=float(raw["weight"]),
    )


def _parse_field(raw: dict[str, Any] | None) -> _FieldSpec | None:
    if raw is None:
        return None
    return _FieldSpec(offset=int(raw["offset"]), length=int(raw["len"]))


def load_fingerprints(path: str | Path = DEFAULT_FINGERPRINTS_PATH) -> list[_FamilySpec]:
    """Parse ``fingerprints.yaml`` into typed family specs, in file order."""
    with open(path, encoding="utf-8") as f:
        raw_entries = yaml.safe_load(f) or []
    specs = []
    for entry in raw_entries:
        specs.append(
            _FamilySpec(
                family=entry["family"],
                display_name=entry["display_name"],
                platform=entry.get("platform"),
                tier=entry["tier"],
                signatures=[_parse_signature(s) for s in entry.get("signatures", [])],
                model_at=_parse_field(entry.get("model_at")),
                serial_at=_parse_field(entry.get("serial_at")),
            )
        )
    return specs


def _read_ascii_field(r: EvidenceReader, field: _FieldSpec) -> str | None:
    if field.offset + field.length > r.size:
        return None
    raw = r.read(field.offset, field.length)
    text = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    return text or None


def _match_one(r: EvidenceReader, spec: _FamilySpec) -> VendorMatch:
    evidence: list[str] = []
    total_weight = 0.0
    for sig in spec.signatures:
        end = min(sig.end, r.size) if sig.end is not None else r.size
        start = min(sig.start, r.size)
        if start >= end:
            continue
        window = r.read(start, end - start)
        offset = window.find(sig.literal)
        if offset != -1:
            abs_offset = start + offset
            total_weight += sig.weight
            evidence.append(
                f"signature {sig.literal!r} at 0x{abs_offset:x} (weight {sig.weight})"
            )
    confidence = min(1.0, total_weight)
    model = _read_ascii_field(r, spec.model_at) if spec.model_at and confidence > 0 else None
    serial = _read_ascii_field(r, spec.serial_at) if spec.serial_at and confidence > 0 else None
    return VendorMatch(
        family=spec.family,
        display_name=spec.display_name,
        platform=spec.platform,
        tier=spec.tier,  # type: ignore[arg-type]
        confidence=confidence,
        evidence=evidence,
        model=model,
        serial=serial,
        fs_version=None,
    )


def match(
    r: EvidenceReader, fingerprints_path: str | Path = DEFAULT_FINGERPRINTS_PATH
) -> list[VendorMatch]:
    """Match ``r`` against every family in ``fingerprints.yaml``.

    Returns every family (including zero-confidence ones, e.g. ``gensim``),
    sorted by confidence descending, then by the family's declaration order
    in the YAML (deterministic tie-break) so the top of the list is always
    the same for the same image.
    """
    specs = load_fingerprints(fingerprints_path)
    matches = [_match_one(r, spec) for spec in specs]
    order = {spec.family: i for i, spec in enumerate(specs)}
    matches.sort(key=lambda m: (-m.confidence, order[m.family]))
    return matches
