"""``pramaan_logs.parse_logs`` against the real corpus
(docs/01-FORENSIC-CORE.md §5 "Logs: all ground-truth log events found,
including carved ones after format").
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from pramaan_core.evidence import EvidenceReader
from pramaan_logs import parse_logs
from pramaan_logs.dhlg import MalformedRecord as DhlgMalformedRecord
from pramaan_logs.dhlg import parse_record as parse_dhlg_record
from pramaan_logs.rats import MalformedRecord as RatsMalformedRecord
from pramaan_logs.rats import parse_record as parse_rats_record

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = REPO_ROOT / "corpus" / "images"
TRUTH_DIR = REPO_ROOT / "corpus" / "truth"


def _skip_if_missing(image: str) -> None:
    if not (IMAGES_DIR / f"{image}.img").exists():
        pytest.skip(f"corpus/images/{image}.img not generated yet — run `just corpus` first")


def _iso_to_us(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1_000_000)


@pytest.mark.slow
@pytest.mark.parametrize(
    ("image", "family"),
    [
        ("hiksim_clean", "hiksim"),
        ("hiksim_clockchange", "hiksim"),
        ("hiksim_format", "hiksim"),
        ("dhsim_format", "dhsim"),
        ("dhsim_expiry", "dhsim"),
    ],
)
def test_parse_logs_finds_every_ground_truth_event(image: str, family: str) -> None:
    _skip_if_missing(image)
    truth = json.loads((TRUTH_DIR / f"{image}.json").read_text())["log_events"]

    with EvidenceReader.open(str(IMAGES_DIR / f"{image}.img")) as r:
        events = parse_logs(r, family)

    assert len(events) == len(truth)
    truth_by_offset = {t["offset"]: t for t in truth}
    for e in events:
        t = truth_by_offset[e.offset]
        assert e.kind == t["kind"]
        assert e.user == t["user"]
        assert e.ts_device_us == _iso_to_us(t["ts_device"])


@pytest.mark.slow
def test_time_change_details_carry_old_and_new_timestamps() -> None:
    _skip_if_missing("hiksim_clockchange")
    with EvidenceReader.open(str(IMAGES_DIR / "hiksim_clockchange.img")) as r:
        events = parse_logs(r, "hiksim")
    tc = next(e for e in events if e.kind == "time_change")
    assert "old_ts_us" in tc.details
    assert "new_ts_us" in tc.details
    # This corpus's clockchange scenario sets the clock *back* by an hour,
    # so old_ts_us > new_ts_us here — just assert they're distinct,
    # positive, plausible unix microsecond values.
    assert tc.details["new_ts_us"] != tc.details["old_ts_us"]
    assert tc.details["new_ts_us"] > 0
    assert tc.details["old_ts_us"] > 0


@pytest.mark.slow
def test_expiry_actor_comes_from_a_correlated_logout_event() -> None:
    """DHSIM has no ``hdd_format`` for an automatic expiry, but the
    corpus's own "system"-user logout right after the last live recording
    is a reasonable, correlated proxy (docs/progress/C3.md "Decisions")."""
    _skip_if_missing("dhsim_expiry")
    truth = json.loads((TRUTH_DIR / "dhsim_expiry.json").read_text())["deletions"]
    assert truth and truth[0]["actor"] == "system"
    with EvidenceReader.open(str(IMAGES_DIR / "dhsim_expiry.img")) as r:
        events = parse_logs(r, "dhsim")
    assert any(e.kind == "logout" and e.user == "system" for e in events)


@pytest.mark.parametrize("family", ["hwsim", "xsim", "gensim", "unknown"])
def test_parse_logs_returns_empty_for_undocumented_families(family: str, tmp_path: Path) -> None:
    """docs/01-FORENSIC-CORE.md §4.9 only documents HIKSIM/DHSIM backends;
    every other family must return an empty list, never raise."""
    img = tmp_path / "junk.img"
    img.write_bytes(b"\x00" * 4096)
    with EvidenceReader.open(str(img)) as r:
        assert parse_logs(r, family) == []


def test_parse_logs_never_raises_on_a_tiny_garbage_image(tmp_path: Path) -> None:
    img = tmp_path / "tiny.img"
    img.write_bytes(b"\x01\x02\x03")
    with EvidenceReader.open(str(img)) as r:
        assert parse_logs(r, "hiksim") == []
        assert parse_logs(r, "dhsim") == []


def test_rats_record_rejects_bad_magic() -> None:
    with pytest.raises(RatsMalformedRecord):
        parse_rats_record(b"\x00" * 64, 0, 0)


def test_dhlg_record_rejects_bad_magic() -> None:
    with pytest.raises(DhlgMalformedRecord):
        parse_dhlg_record(b"\x00" * 32, 0, 0)


def test_dhlg_record_round_trip() -> None:
    import struct

    from pramaan_logs.dhlg import parse_record

    body = bytearray(32)
    body[0:4] = b"DHLG"
    struct.pack_into("<I", body, 4, 1_700_000_000)
    struct.pack_into("<H", body, 8, 0x01)  # login
    struct.pack_into("<H", body, 10, 2)
    body[12:17] = b"admin"
    struct.pack_into("<I", body, 28, 42)
    rec = parse_record(bytes(body), 100, 100)
    assert rec.kind == "login"
    assert rec.channel == 2
    assert rec.user == "admin"
    assert rec.param == 42
