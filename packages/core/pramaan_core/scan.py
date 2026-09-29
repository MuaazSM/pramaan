"""Signature / Annex B start-code scanner: one interface, two backends.

`docs/01-FORENSIC-CORE.md` §4.3: a Rust backend (`crates/scanner`, PyO3
module ``pramaan_scanner``) and an identical pure-Python fallback, selected
by :func:`backend`. The Rust extension is optional at runtime — built by
``maturin develop --features python`` (see ``just setup``); when it isn't
importable, or ``PRAMAAN_SCANNER_BACKEND=python`` is set, this module falls
back to the implementation below (``mmap``/``EvidenceReader.read`` + ``re``
+ NumPy entropy, per §4.3/§6).

Both backends:

- Read evidence exclusively through :class:`pramaan_core.evidence.EvidenceReader`
  (read-only; ``mmap_readonly()`` uses ``ACCESS_READ`` — CLAUDE.md rule 1).
  The Rust backend currently supports raw images only (it opens the path
  itself, read-only, via ``memmap2``); E01 images always use this Python
  fallback, which reads through ``EvidenceReader`` and therefore also
  supports E01 (when ``pyewf`` is installed).
- Partition ``[start, end)`` into non-overlapping *core* windows of
  ``window`` bytes (default 64 MiB) searched with an overlap so a match
  spanning a window boundary is found exactly once, by whichever window's
  core contains its start offset. See ``crates/scanner/src/windows.rs`` for
  the exact algorithm this module mirrors.
- Agree on offsets, NAL type decoding and entropy byte-for-byte (parity
  tests: ``tests/core/test_scan.py``), except that ``byte_histogram``
  entropy values may differ by a few ULPs between backends due to
  floating-point summation order (NumPy's pairwise sum vs. Rust's
  sequential loop) — parity tests use an approximate comparison for that
  one function.
"""

from __future__ import annotations

import os
import re
from typing import Any, Literal

import numpy as np

from pramaan_core.evidence import EvidenceReader

#: Env var to force a backend. Unset or any other value: autodetect (Rust
#: if `pramaan_scanner` is importable, else Python).
BACKEND_ENV_VAR = "PRAMAAN_SCANNER_BACKEND"

#: Default window size: 64 MiB, per docs/01-FORENSIC-CORE.md §4.3.
DEFAULT_WINDOW = 64 * 1024 * 1024

#: Bytes of overlap past a window's core end needed to always see the NAL
#: header byte after a start code found near the boundary. Must match
#: `crates/scanner/src/annexb.rs::ANNEXB_OVERLAP`.
_ANNEXB_OVERLAP = 8

_START_CODE_TAIL = b"\x00\x00\x01"

#: "Plausible" NAL types used by `codec="auto"` to disambiguate H.264 vs.
#: H.265 from a single header byte (docs/01-FORENSIC-CORE.md §4.8). Must
#: match `crates/scanner/src/annexb.rs`.
_H264_PLAUSIBLE = frozenset({1, 5, 7, 8})
_H265_PLAUSIBLE = frozenset({1, 19, 20, 32, 33, 34})

Codec = Literal["h264", "h265", "auto"]

SignatureHit = tuple[int, int]
NalHit = tuple[int, int, int, str]


class UnknownCodec(ValueError):
    """Raised by ``scan_annexb`` for a ``codec`` other than h264/h265/auto."""


class BackendUnavailable(RuntimeError):
    """Raised when ``PRAMAAN_SCANNER_BACKEND=rust`` is forced but the
    ``pramaan_scanner`` extension module isn't importable."""


_rust_import_error: Exception | None = None
_rust_module_cache: Any | None = None
_rust_import_attempted = False


def _rust_module() -> Any | None:
    """Lazily imports and caches the ``pramaan_scanner`` extension module.

    Returns ``None`` (caching the failure) if it isn't importable.
    """
    global _rust_module_cache, _rust_import_attempted, _rust_import_error
    if not _rust_import_attempted:
        _rust_import_attempted = True
        try:
            import pramaan_scanner

            _rust_module_cache = pramaan_scanner
        except ImportError as exc:  # pragma: no cover - depends on environment
            _rust_import_error = exc
            _rust_module_cache = None
    return _rust_module_cache


def _require_rust_module() -> Any:
    """Like :func:`_rust_module`, but for call sites that only reach here
    after `backend() == "rust"` has already confirmed it's importable."""
    mod = _rust_module()
    assert mod is not None, "backend() == 'rust' implies _rust_module() is not None"
    return mod


def backend() -> Literal["rust", "python"]:
    """Returns which backend :func:`scan_signatures`/`scan_annexb`/`byte_histogram`
    will use: ``"rust"`` if the ``pramaan_scanner`` extension is importable
    (or forced via ``PRAMAAN_SCANNER_BACKEND=rust``), else ``"python"``.
    """
    override = os.environ.get(BACKEND_ENV_VAR)
    if override == "python":
        return "python"
    if override == "rust":
        if _rust_module() is None:
            raise BackendUnavailable(
                f"{BACKEND_ENV_VAR}=rust was set but the 'pramaan_scanner' "
                "extension module is not importable; build it with "
                "'maturin develop --features python' (see docs/05-INFRA-QA.md §2), "
                f"or unset {BACKEND_ENV_VAR}. Import error: {_rust_import_error!r}"
            )
        return "rust"
    return "rust" if _rust_module() is not None else "python"


def _core_windows(start: int, end: int, window: int) -> list[tuple[int, int]]:
    """Partitions ``[start, end)`` into consecutive core ranges of at most
    ``window`` bytes. Mirrors ``crates/scanner/src/windows.rs::core_windows``.
    """
    if window <= 0:
        raise ValueError("window must be positive")
    out: list[tuple[int, int]] = []
    if start >= end:
        return out
    s = start
    while s < end:
        e = min(s + window, end)
        out.append((s, e))
        s = e
    return out


# ---------------------------------------------------------------------------
# scan_signatures
# ---------------------------------------------------------------------------


def scan_signatures(
    path: str,
    patterns: list[bytes],
    start: int = 0,
    end: int | None = None,
    window: int = DEFAULT_WINDOW,
) -> list[SignatureHit]:
    """Finds every occurrence of every pattern in ``patterns`` within the
    evidence image at ``path``, restricted to ``[start, end)`` (``end=None``
    means end of image). Returns ``(pattern_idx, offset)`` pairs — the
    pattern's index in ``patterns`` and the absolute byte offset of the
    match — sorted by ``(offset, pattern_idx)``.
    """
    if backend() == "rust":
        mod = _require_rust_module()
        return list(mod.scan_signatures(path, patterns, start, end, window))
    return _scan_signatures_python(path, patterns, start, end, window)


def _pattern_alternation(patterns: list[bytes]) -> re.Pattern[bytes]:
    # One capturing group per pattern (by position, not de-duplicated by
    # content) so `m.lastindex - 1` always recovers the *original* list
    # index, even if two entries in `patterns` are byte-identical.
    parts = [b"(" + re.escape(p) + b")" for p in patterns]
    return re.compile(b"|".join(parts), re.DOTALL)


def _scan_signatures_python(
    path: str,
    patterns: list[bytes],
    start: int,
    end: int | None,
    window: int,
) -> list[SignatureHit]:
    if not patterns:
        return []
    overlap = max(len(p) for p in patterns) - 1
    pattern_re = _pattern_alternation(patterns)
    hits: list[SignatureHit] = []
    with EvidenceReader.open(path) as reader:
        real_end = reader.size if end is None else min(end, reader.size)
        real_start = min(start, real_end)
        for core_start, core_end in _core_windows(real_start, real_end, window):
            search_end = min(core_end + overlap, real_end)
            buf = reader.read(core_start, search_end - core_start)
            for m in pattern_re.finditer(buf):
                abs_offset = core_start + m.start()
                if abs_offset < core_end:
                    assert m.lastindex is not None
                    hits.append((m.lastindex - 1, abs_offset))
    hits.sort()
    return hits


# ---------------------------------------------------------------------------
# scan_annexb
# ---------------------------------------------------------------------------


def scan_annexb(
    path: str,
    start: int = 0,
    end: int | None = None,
    codec: Codec = "auto",
    window: int = DEFAULT_WINDOW,
) -> list[NalHit]:
    """Finds Annex B start codes within ``[start, end)`` and decodes the NAL
    type that follows each one. Returns
    ``(offset, start_code_len, nal_type, codec)`` tuples sorted by offset;
    ``offset`` is the absolute offset of the start code itself (the leading
    zero of a 3- or 4-byte code), ``codec`` is ``"h264"`` or ``"h265"``.

    ``codec="auto"`` decodes both interpretations of the header byte and
    picks whichever NAL type is "plausible" (docs/01-FORENSIC-CORE.md §4.8);
    a single header byte can't unambiguously distinguish the two codecs, so
    this is a documented heuristic, not a guarantee.
    """
    if codec not in ("h264", "h265", "auto"):
        raise UnknownCodec(f"unknown codec {codec!r}; expected 'h264', 'h265' or 'auto'")
    if backend() == "rust":
        mod = _require_rust_module()
        return [tuple(h) for h in mod.scan_annexb(path, start, end, codec, window)]
    return _scan_annexb_python(path, start, end, codec, window)


def _h264_type(header_byte: int) -> int:
    return header_byte & 0x1F


def _h265_type(header_byte: int) -> int:
    return (header_byte >> 1) & 0x3F


def _decode_nal(header_byte: int, codec: Codec) -> tuple[int, str]:
    if codec == "h264":
        return _h264_type(header_byte), "h264"
    if codec == "h265":
        return _h265_type(header_byte), "h265"
    h264 = _h264_type(header_byte)
    h265 = _h265_type(header_byte)
    if h264 in _H264_PLAUSIBLE:
        return h264, "h264"
    if h265 in _H265_PLAUSIBLE:
        return h265, "h265"
    return h264, "h264"


def _scan_annexb_python(
    path: str,
    start: int,
    end: int | None,
    codec: Codec,
    window: int,
) -> list[NalHit]:
    hits: list[NalHit] = []
    with EvidenceReader.open(path) as reader:
        real_end = reader.size if end is None else min(end, reader.size)
        real_start = min(start, real_end)
        for core_start, core_end in _core_windows(real_start, real_end, window):
            # Capped at `real_end` (the requested end), matching
            # `scan_signatures`/`crates/scanner/src/annexb.rs`: overlap only
            # looks within the requested range, never past it.
            search_end = min(core_end + _ANNEXB_OVERLAP, real_end)
            buf = reader.read(core_start, search_end - core_start)
            idx = 0
            while True:
                pos = buf.find(_START_CODE_TAIL, idx)
                if pos == -1:
                    break
                idx = pos + 1
                abs_pos = core_start + pos
                if abs_pos >= core_end:
                    continue
                header_local = pos + 3
                if core_start + header_local >= real_end or header_local >= len(buf):
                    continue
                four_byte = pos >= 1 and buf[pos - 1] == 0x00
                offset = abs_pos - 1 if four_byte else abs_pos
                start_code_len = 4 if four_byte else 3
                nal_type, codec_name = _decode_nal(buf[header_local], codec)
                hits.append((offset, start_code_len, nal_type, codec_name))
    hits.sort(key=lambda h: h[0])
    return hits


# ---------------------------------------------------------------------------
# byte_histogram
# ---------------------------------------------------------------------------


def byte_histogram(
    path: str,
    start: int = 0,
    end: int | None = None,
    block: int = 1024 * 1024,
) -> list[float]:
    """Computes Shannon entropy (bits/byte, ``0.0..=8.0``) for every
    ``block``-byte block of ``[start, end)`` (the final block may be
    shorter). Finds zeroed / wiped (entropy near 0) vs. dense video or
    compressed data (entropy near 8) regions.
    """
    if backend() == "rust":
        mod = _require_rust_module()
        return list(mod.byte_histogram(path, start, end, block))
    return _byte_histogram_python(path, start, end, block)


def _entropy(chunk: bytes) -> float:
    if not chunk:
        return 0.0
    counts = np.bincount(np.frombuffer(chunk, dtype=np.uint8), minlength=256).astype(np.float64)
    total = float(len(chunk))
    probs = counts / total
    nonzero = probs > 0
    return float(-np.sum(probs[nonzero] * np.log2(probs[nonzero])))


def _byte_histogram_python(
    path: str,
    start: int,
    end: int | None,
    block: int,
) -> list[float]:
    if block <= 0:
        raise ValueError("block must be positive")
    hist: list[float] = []
    with EvidenceReader.open(path) as reader:
        real_end = reader.size if end is None else min(end, reader.size)
        real_start = min(start, real_end)
        offset = real_start
        while offset < real_end:
            n = min(block, real_end - offset)
            hist.append(_entropy(reader.read(offset, n)))
            offset += n
    return hist
