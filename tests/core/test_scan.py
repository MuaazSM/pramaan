"""Scanner parity: `pramaan_core.scan`'s Rust and pure-Python backends must
agree, `docs/01-FORENSIC-CORE.md` §4.3/§5 ("Scanner parity: Rust and Python
backends return identical hit lists on every corpus image").

`scan_signatures`/`scan_annexb` are compared for byte-exact equality;
`byte_histogram` is compared with a floating-point tolerance (see
`pramaan_core/scan.py`'s module docstring for why).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from pramaan_core import scan

RUST_AVAILABLE = scan._rust_module() is not None  # noqa: SLF001 - internal test hook

_BACKENDS = ["python", *(["rust"] if RUST_AVAILABLE else [])]


@pytest.fixture(params=_BACKENDS)
def backend_name(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Runs the test once per available backend, forced via the env override."""
    monkeypatch.setenv(scan.BACKEND_ENV_VAR, request.param)
    assert scan.backend() == request.param
    return str(request.param)


def _write(tmp_path: Path, data: bytes, name: str = "image.raw") -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


# ---------------------------------------------------------------------------
# backend() / env override
# ---------------------------------------------------------------------------


def test_backend_defaults_to_rust_when_available_else_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(scan.BACKEND_ENV_VAR, raising=False)
    assert scan.backend() == ("rust" if RUST_AVAILABLE else "python")


def test_backend_env_forces_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(scan.BACKEND_ENV_VAR, "python")
    assert scan.backend() == "python"


@pytest.mark.skipif(RUST_AVAILABLE, reason="only meaningful when the Rust extension is absent")
def test_backend_env_rust_raises_when_extension_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(scan.BACKEND_ENV_VAR, "rust")
    with pytest.raises(scan.BackendUnavailable):
        scan.backend()


# ---------------------------------------------------------------------------
# scan_signatures — per-backend functional tests
# ---------------------------------------------------------------------------


def test_scan_signatures_finds_planted_patterns(tmp_path: Path, backend_name: str) -> None:
    data = bytearray(os.urandom(5000))
    data[123:123 + 13] = b"HIKVISION@HAN"
    data[4000:4000 + 8] = b"HIKBTREE"
    path = _write(tmp_path, bytes(data))

    hits = scan.scan_signatures(path, [b"HIKVISION@HAN", b"HIKBTREE"])

    assert (0, 123) in hits
    assert (1, 4000) in hits
    assert len(hits) == 2


def test_scan_signatures_respects_start_end(tmp_path: Path, backend_name: str) -> None:
    data = b"AAAA needle AAAA needle AAAA"
    path = _write(tmp_path, data)

    hits = scan.scan_signatures(path, [b"needle"], start=0, end=15)

    assert hits == [(0, 5)]


def test_scan_signatures_boundary_spanning_match_is_found_exactly_once(
    tmp_path: Path, backend_name: str
) -> None:
    # Plant the pattern straddling a deliberately small window (64 bytes),
    # at several offsets relative to the boundary, and check each is found
    # exactly once (not missed, not double-counted).
    pattern = b"BOUNDARYSIGNATURE"
    window = 64
    for straddle_offset in (window - 5, window - 1, window, window + 3):
        data = bytearray(os.urandom(400))
        data[straddle_offset:straddle_offset + len(pattern)] = pattern
        path = _write(tmp_path, bytes(data), name=f"boundary_{straddle_offset}.raw")

        hits = scan.scan_signatures(path, [pattern], window=window)

        matches = [h for h in hits if h[1] == straddle_offset]
        assert matches == [(0, straddle_offset)], (straddle_offset, hits)


# ---------------------------------------------------------------------------
# scan_annexb — per-backend functional tests
# ---------------------------------------------------------------------------


def test_scan_annexb_decodes_h264_idr_three_byte_start_code(
    tmp_path: Path, backend_name: str
) -> None:
    data = bytes([0xAB, 0xAB]) + bytes([0x00, 0x00, 0x01, 0x65]) + os.urandom(10)
    path = _write(tmp_path, data)

    hits = scan.scan_annexb(path, codec="h264")

    assert hits == [(2, 3, 5, "h264")]


def test_scan_annexb_decodes_four_byte_start_code(tmp_path: Path, backend_name: str) -> None:
    data = bytes([0x00, 0x00, 0x00, 0x01, 0x67]) + os.urandom(10)  # SPS, type 7
    path = _write(tmp_path, data)

    hits = scan.scan_annexb(path, codec="h264")

    assert hits == [(0, 4, 7, "h264")]


def test_scan_annexb_auto_codec_detects_h265_vps(tmp_path: Path, backend_name: str) -> None:
    # header byte 0x40 -> h264 type 0 (not plausible), h265 type 32 (VPS, plausible)
    data = bytes([0x00, 0x00, 0x01, 0x40]) + os.urandom(10)
    path = _write(tmp_path, data)

    hits = scan.scan_annexb(path, codec="auto")

    assert hits == [(0, 3, 32, "h265")]


def test_scan_annexb_unknown_codec_raises(tmp_path: Path, backend_name: str) -> None:
    path = _write(tmp_path, b"\x00\x00\x01\x65")
    with pytest.raises(scan.UnknownCodec):
        scan.scan_annexb(path, codec="mpeg2")  # type: ignore[arg-type]


def test_scan_annexb_boundary_spanning_start_code_is_found_exactly_once(
    tmp_path: Path, backend_name: str
) -> None:
    window = 64
    for straddle_offset in (window - 5, window - 1, window, window + 3):
        data = bytearray(os.urandom(400))
        # Ensure no accidental extra start codes in the random filler.
        data = bytearray(b"\xab" * 400)
        data[straddle_offset:straddle_offset + 4] = bytes([0x00, 0x00, 0x01, 0x65])
        path = _write(tmp_path, bytes(data), name=f"annexb_boundary_{straddle_offset}.raw")

        hits = scan.scan_annexb(path, codec="h264", window=window)

        assert hits == [(straddle_offset, 3, 5, "h264")], (straddle_offset, hits)


# ---------------------------------------------------------------------------
# byte_histogram — per-backend functional tests
# ---------------------------------------------------------------------------


def test_byte_histogram_zeroed_region_is_zero_entropy(tmp_path: Path, backend_name: str) -> None:
    path = _write(tmp_path, bytes(4096))

    hist = scan.byte_histogram(path, block=1024)

    assert hist == [0.0, 0.0, 0.0, 0.0]


def test_byte_histogram_last_block_may_be_shorter(tmp_path: Path, backend_name: str) -> None:
    path = _write(tmp_path, os.urandom(1500))

    hist = scan.byte_histogram(path, block=1024)

    assert len(hist) == 2


# ---------------------------------------------------------------------------
# Explicit cross-backend parity (skipped if the Rust extension isn't built)
# ---------------------------------------------------------------------------

pytestmark_rust_required = pytest.mark.skipif(
    not RUST_AVAILABLE, reason="pramaan_scanner extension not built (maturin/Rust unavailable)"
)


@pytestmark_rust_required
def test_parity_scan_signatures_random_buffer_with_planted_hits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = bytearray(os.urandom(300_000))
    patterns = [b"HIKVISION@HANGZHOU", b"DHFS4.1\x00", b"HONEYWELL-NVR-SIM\x00"]
    # Plant several hits, including ones straddling a small window boundary.
    plant_positions = [0, 50, 4096 - 5, 4096, 4096 + 10, 150_000, 299_990]
    for i, pos in enumerate(plant_positions):
        pattern = patterns[i % len(patterns)]
        end = pos + len(pattern)
        if end > len(data):
            continue
        data[pos:end] = pattern
    path = _write(tmp_path, bytes(data))

    monkeypatch.setenv(scan.BACKEND_ENV_VAR, "rust")
    rust_hits = scan.scan_signatures(path, patterns, window=4096)
    monkeypatch.setenv(scan.BACKEND_ENV_VAR, "python")
    python_hits = scan.scan_signatures(path, patterns, window=4096)

    assert rust_hits == python_hits
    assert len(rust_hits) > 0


@pytestmark_rust_required
def test_parity_scan_annexb_random_buffer_with_planted_start_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = bytearray(os.urandom(300_000))
    nal_headers_h264 = [0x67, 0x68, 0x65, 0x41]  # SPS, PPS, IDR, non-IDR
    plant_positions = [0, 10, 4096 - 4, 4096, 4096 + 8, 200_000]
    for i, pos in enumerate(plant_positions):
        header = nal_headers_h264[i % len(nal_headers_h264)]
        four_byte = i % 2 == 0
        code = (
            bytes([0x00, 0x00, 0x00, 0x01, header])
            if four_byte
            else bytes([0x00, 0x00, 0x01, header])
        )
        write_pos = pos - 1 if four_byte else pos
        end = write_pos + len(code)
        if write_pos < 0 or end > len(data):
            continue
        data[write_pos:end] = code
    path = _write(tmp_path, bytes(data))

    monkeypatch.setenv(scan.BACKEND_ENV_VAR, "rust")
    rust_hits = scan.scan_annexb(path, codec="h264", window=4096)
    monkeypatch.setenv(scan.BACKEND_ENV_VAR, "python")
    python_hits = scan.scan_annexb(path, codec="h264", window=4096)

    assert rust_hits == python_hits
    assert len(rust_hits) > 0


@pytestmark_rust_required
def test_parity_byte_histogram_approximately_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = os.urandom(200_000)
    path = _write(tmp_path, data)

    monkeypatch.setenv(scan.BACKEND_ENV_VAR, "rust")
    rust_hist = scan.byte_histogram(path, block=4096)
    monkeypatch.setenv(scan.BACKEND_ENV_VAR, "python")
    python_hist = scan.byte_histogram(path, block=4096)

    assert len(rust_hist) == len(python_hist)
    for r, p in zip(rust_hist, python_hist, strict=True):
        assert r == pytest.approx(p, rel=1e-9, abs=1e-9)


# ---------------------------------------------------------------------------
# Performance target: 512 MiB scanned in < 5 s with the Rust backend.
# Generated in tmp_path and deleted immediately after — this machine has
# only ~13 GiB free disk.
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytestmark_rust_required
def test_512mib_scan_under_5s_with_rust(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(scan.BACKEND_ENV_VAR, raising=False)
    assert scan.backend() == "rust"

    size = 512 * 1024 * 1024
    path = tmp_path / "big.raw"
    try:
        with open(path, "wb") as f:
            written = 0
            block = 8 * 1024 * 1024
            while written < size:
                f.write(os.urandom(block))
                written += block

        patterns = [
            b"HIKVISION@HANGZHOU",
            b"DHFS4.1\x00",
            b"HONEYWELL-NVR-SIM\x00",
            b"XVR-GENERIC-2026",
        ]
        t0 = time.monotonic()
        scan.scan_signatures(str(path), patterns)
        scan.scan_annexb(str(path))
        elapsed = time.monotonic() - t0

        assert elapsed < 5.0, f"512 MiB signature+Annex B scan took {elapsed:.2f}s (target < 5s)"
    finally:
        path.unlink(missing_ok=True)
