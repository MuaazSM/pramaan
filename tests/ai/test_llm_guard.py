"""Payload guard tests (docs/03-AI-TIMELINE.md §8.2/§9, CLAUDE.md rule 6).

Table-driven: every case that must be rejected, and a handful that must be
accepted (only structured metadata passes).
"""

from __future__ import annotations

import base64

import pytest
from pramaan_llm.guard import PayloadGuardViolation, payload_guard


def test_accepts_structured_metadata() -> None:
    payload_guard(
        {
            "channels": [1, 2, 3],
            "from_ist": "2026-03-10T20:00:00+05:30",
            "count": 5,
            "confidence": 0.87,
            "verdict": "recovered",
            "notes": "short string, well under the limit",
        }
    )


def test_accepts_nested_lists_and_dicts() -> None:
    payload_guard(
        {
            "facts": [
                {"id": "fact_1", "text": "Recording gap on CH2 from 20:00 to 09:00."},
                {"id": "fact_2", "text": "37 seconds of OSD drift on CH2."},
            ]
        }
    )


def test_rejects_raw_bytes() -> None:
    with pytest.raises(PayloadGuardViolation):
        payload_guard({"data": b"\x00\x01\x02\x03"})


def test_rejects_bytes_nested_in_a_list() -> None:
    with pytest.raises(PayloadGuardViolation):
        payload_guard({"items": [1, 2, b"raw"]})


@pytest.mark.parametrize(
    "key",
    ["frame", "frames", "thumb", "thumbnail", "image", "images", "pixels", "jpeg", "png"],
)
def test_rejects_forbidden_key_names(key: str) -> None:
    with pytest.raises(PayloadGuardViolation):
        payload_guard({key: "anything at all"})


def test_forbidden_key_check_is_case_insensitive() -> None:
    with pytest.raises(PayloadGuardViolation):
        payload_guard({"FrameBytes": "x"})


def test_rejects_long_base64_looking_string() -> None:
    encoded = base64.b64encode(b"0" * 300).decode("ascii")
    with pytest.raises(PayloadGuardViolation):
        payload_guard({"note": encoded})


def test_rejects_long_hex_looking_string() -> None:
    with pytest.raises(PayloadGuardViolation):
        payload_guard({"note": "ab" * 200})


def test_accepts_long_plain_english_string() -> None:
    # Long, but not base64/hex-shaped — must be allowed through.
    payload_guard({"note": "This is a long sentence. " * 20})


def test_rejects_oversize_payload() -> None:
    with pytest.raises(PayloadGuardViolation):
        payload_guard({"notes": ["short entry"] * 5000}, max_payload_bytes=1024)


def test_violation_reports_a_path() -> None:
    try:
        payload_guard({"outer": {"inner": [1, 2, b"x"]}})
    except PayloadGuardViolation as exc:
        assert "outer" in exc.path
        assert "inner" in exc.path
    else:
        pytest.fail("expected PayloadGuardViolation")
