"""SPS bit-reader tests (docs/01-FORENSIC-CORE.md §4.7 step 3).

Uses a real SPS produced by ffmpeg (baseline profile, matching the
synthetic corpus's own encode settings) rather than a hand-crafted
bitstream, so the parser is exercised against a real encoder's output.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest
from pramaan_recovery.sps import MalformedSps, parse_sps, strip_emulation_prevention

FFMPEG = shutil.which("ffmpeg")


def _find_first_sps(annexb: bytes) -> bytes:
    """Return the RBSP (NAL header byte stripped) of the first SPS NAL
    (type 7) in an Annex B stream — a tiny inline scanner independent of
    ``pramaan_formats.nalutil`` so this test doesn't depend on that module."""
    i = 0
    n = len(annexb)
    marks = []
    while i < n - 2:
        if annexb[i] == 0 and annexb[i + 1] == 0 and annexb[i + 2] == 1:
            marks.append(i + 3)
            i += 3
        else:
            i += 1
    for idx, start in enumerate(marks):
        end = marks[idx + 1] if idx + 1 < len(marks) else n
        nal_type = annexb[start] & 0x1F
        if nal_type == 7:
            return annexb[start + 1 : end]
    raise AssertionError("no SPS NAL found")


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not on PATH")
def test_parses_a_real_baseline_sps_640x360() -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=640x360:d=1:r=5",
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-pix_fmt",
        "yuv420p",
        "-frames:v",
        "1",
        "-f",
        "h264",
        "-",
    ]
    out = subprocess.run(cmd, capture_output=True, check=True)
    rbsp = _find_first_sps(out.stdout)
    info = parse_sps(rbsp)
    assert info.width == 640
    assert info.height == 360


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not on PATH")
def test_parses_a_real_baseline_sps_1280x720_with_cropping() -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=1280x720:d=1:r=5",
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-pix_fmt",
        "yuv420p",
        "-frames:v",
        "1",
        "-f",
        "h264",
        "-",
    ]
    out = subprocess.run(cmd, capture_output=True, check=True)
    rbsp = _find_first_sps(out.stdout)
    info = parse_sps(rbsp)
    assert info.width == 1280
    assert info.height == 720


def test_strip_emulation_prevention_removes_only_true_ep_bytes() -> None:
    assert strip_emulation_prevention(b"\x00\x00\x03\x01") == b"\x00\x00\x01"
    assert strip_emulation_prevention(b"\x00\x00\x03\x02") == b"\x00\x00\x02"
    assert strip_emulation_prevention(b"\x00\x00\x03\x03") == b"\x00\x00\x03"
    # 0x03 not followed by a byte <= 3 is real data, not an EP byte.
    assert strip_emulation_prevention(b"\x00\x00\x03\x04") == b"\x00\x00\x03\x04"
    assert strip_emulation_prevention(b"\x01\x02\x03\x04") == b"\x01\x02\x03\x04"


def test_parse_sps_too_short_raises() -> None:
    with pytest.raises(MalformedSps):
        parse_sps(b"\x00")
