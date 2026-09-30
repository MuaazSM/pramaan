"""Real-mode signed MP4 export (task B3, docs/02-BACKEND.md §10, §12).

Acceptance covered here: "Export | Exported MP4 plays; verify endpoint
returns valid; flipping one byte → invalid."
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pramaan_core.ids import content_id
from pramaan_core.models import ByteRange, FrameRef, Recording, VendorMatch
from pramaan_worker import registry

PAD = 128
FFMPEG_TIMEOUT_S = 30


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True, timeout=5)
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not available")


@pytest.fixture(autouse=True)
def _reset_registry_around_test() -> Iterator[None]:
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


def _build_two_gop_h264(tmp_path: Path) -> bytes:
    out = tmp_path / "gop.h264"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=size=64x64:rate=2:color=green",
            "-frames:v", "2", "-c:v", "libx264", "-profile:v", "baseline", "-g", "1",
            "-f", "h264", str(out),
        ],
        check=True, capture_output=True, timeout=FFMPEG_TIMEOUT_S,
    )
    return out.read_bytes()


def _nal_sps_starts(data: bytes) -> list[int]:
    import re

    offs = []
    for m in re.finditer(rb"\x00\x00\x01", data):
        i = m.start()
        off, sc_len = (i - 1, 4) if i >= 1 and data[i - 1] == 0 else (i, 3)
        if data[off + sc_len] & 0x1F == 7:
            offs.append(off)
    return offs


def _fake_vendor_match() -> VendorMatch:
    return VendorMatch(
        family="testvendor", display_name="Test Vendor (fake, in-test)", platform=None,
        tier="A", confidence=0.9, evidence=["fake signature for test_exports_real"],
        model=None, serial=None, fs_version=None,
    )


class _FakeVendorParser:
    family = "testvendor"

    def __init__(self, recording: Recording, frames: list[FrameRef]) -> None:
        self._recording = recording
        self._frames = frames

    def detect(self, reader: Any) -> VendorMatch | None:
        return _fake_vendor_match()

    def list_recordings(self, reader: Any) -> list[Recording]:
        return [self._recording]

    def iter_frames(self, reader: Any, rec: Recording) -> list[FrameRef]:
        return list(self._frames)

    def unindexed_ranges(self, reader: Any) -> list[ByteRange]:
        return []

    def index_state(self, reader: Any) -> dict[str, Any]:
        return {"family": self.family}


def _intake_body() -> dict[str, str]:
    return {
        "seized_at_local": "2026-03-12T16:40:00+05:30",
        "dvr_displayed_time": "2026-03-12T16:45:12",
        "reference_time": "2026-03-12T16:40:00+05:30",
        "reference_source": "NTP phone clock",
        "timezone": "Asia/Kolkata",
        "make_model_label": "Test Vendor DVR (fake)",
        "notes": "fixture for test_exports_real",
    }


def _create_case(client: TestClient, number: str) -> dict[str, Any]:
    resp = client.post("/api/cases", json={"case_number": number, "title": f"Exports {number}"})
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _register_and_scan(
    client: TestClient, tmp_path: Path, real_evidence_dir: Path, case_number: str
) -> tuple[dict[str, Any], str]:
    """Returns ``(case, recording_id)``."""
    case = _create_case(client, case_number)
    image_path = real_evidence_dir / f"{case_number}.img"
    h264 = _build_two_gop_h264(tmp_path)
    sps_starts = _nal_sps_starts(h264)
    assert len(sps_starts) == 2
    chunk_bounds = [*sps_starts, len(h264)]
    chunks = [
        (chunk_bounds[i], chunk_bounds[i + 1] - chunk_bounds[i]) for i in range(len(sps_starts))
    ]

    image_bytes = (b"\x00" * PAD) + h264 + (b"\xff" * PAD)
    image_path.write_bytes(image_bytes)

    ev_resp = client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(image_path), "label": "fake disk", "intake": _intake_body()},
    )
    assert ev_resp.status_code == 201, ev_resp.text
    image = ev_resp.json()

    recording_id = content_id("rec", {"image_id": image["id"], "channel": 0, "start": 0})
    frames = []
    for i, (rel_off, rel_len) in enumerate(chunks):
        payload_offset = PAD + rel_off
        payload = image_bytes[payload_offset : payload_offset + rel_len]
        frames.append(
            FrameRef(
                frame_id=hashlib.sha256(payload).hexdigest()[:24], image_id=image["id"],
                channel=0, stream="main", codec="h264", frame_type="I",
                header_offset=max(payload_offset - 8, 0), payload_offset=payload_offset,
                payload_len=rel_len, ts_header_us=i * 80_000, ts_index_us=i * 80_000,
                width=64, height=64, source="index", recording_id=recording_id, deleted=False,
            )
        )
    span_start = frames[0].payload_offset
    span_end = frames[-1].payload_offset + frames[-1].payload_len
    recording = Recording(
        id=recording_id, image_id=image["id"], channel=0, stream="main", start_ts_us=0,
        end_ts_us=frames[-1].ts_header_us, source="index", deleted=False,
        byte_ranges=[ByteRange(offset=span_start, length=span_end - span_start)],
    )
    registry.register_fingerprinter(lambda reader: [_fake_vendor_match()])
    registry.register_vendor_parser(_FakeVendorParser(recording, frames))

    scan_resp = client.post(f"/api/evidence/{image['id']}/scan", json={})
    assert scan_resp.status_code == 202, scan_resp.text
    assert scan_resp.json()["status"] == "done", scan_resp.json()

    return case, recording_id


def test_create_export_plays_and_verifies(
    real_client: TestClient, tmp_path: Path, real_evidence_dir: Path
) -> None:
    case, recording_id = _register_and_scan(
        real_client, tmp_path, real_evidence_dir, "CR-B3-EXP-0001"
    )

    resp = real_client.post(
        f"/api/cases/{case['id']}/exports", json={"recording_id": recording_id}
    )
    assert resp.status_code == 201, resp.text
    export = resp.json()
    assert export["manifest_sha256"]
    assert export["signature_path"]

    file_resp = real_client.get(f"/api/exports/{export['id']}/file")
    assert file_resp.status_code == 200
    mp4_bytes = file_resp.content
    assert mp4_bytes[4:8] == b"ftyp"

    # Plays: ffprobe reports a real h264 stream, no re-encode (still the
    # source resolution/codec).
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height",
         "-of", "default=nw=1", "-i", "pipe:0"],
        input=mp4_bytes, capture_output=True, timeout=FFMPEG_TIMEOUT_S,
    )
    assert probe.returncode == 0, probe.stderr
    assert b"codec_name=h264" in probe.stdout
    assert b"width=64" in probe.stdout

    verify_resp = real_client.post(
        "/api/exports/verify", files={"file": ("export.mp4", mp4_bytes, "video/mp4")}
    )
    assert verify_resp.status_code == 200, verify_resp.text
    outcome = verify_resp.json()
    assert outcome["signature_valid"] is True
    assert outcome["source_matches_registered_evidence"] is True


def test_export_tamper_detection(
    real_client: TestClient, tmp_path: Path, real_evidence_dir: Path
) -> None:
    case, recording_id = _register_and_scan(
        real_client, tmp_path, real_evidence_dir, "CR-B3-EXP-0002"
    )
    export = real_client.post(
        f"/api/cases/{case['id']}/exports", json={"recording_id": recording_id}
    ).json()
    mp4_bytes = real_client.get(f"/api/exports/{export['id']}/file").content

    good = real_client.post(
        "/api/exports/verify", files={"file": ("export.mp4", mp4_bytes, "video/mp4")}
    ).json()
    assert good["signature_valid"] is True

    tampered = bytearray(mp4_bytes)
    # Flip a byte well inside the video payload (past the ftyp/moov/mdat
    # header, before any trailing manifest/signature box).
    tampered[len(tampered) // 3] ^= 0xFF
    bad = real_client.post(
        "/api/exports/verify", files={"file": ("export.mp4", bytes(tampered), "video/mp4")}
    ).json()
    assert bad["signature_valid"] is False
    assert bad["manifest"].get("_verification_notes")


def test_export_manifest_is_deterministic_across_repeat_calls(
    real_client: TestClient, tmp_path: Path, real_evidence_dir: Path
) -> None:
    """Unlike report generation (self-referential through the custody
    chain — see test_reports_real.py), an export's manifest never embeds
    the custody chain, so repeat exports of the *same* recording by the
    *same* examiner really are byte-identical (content-derived export id)."""
    case, recording_id = _register_and_scan(
        real_client, tmp_path, real_evidence_dir, "CR-B3-EXP-0003"
    )
    first = real_client.post(
        f"/api/cases/{case['id']}/exports", json={"recording_id": recording_id}
    ).json()
    second = real_client.post(
        f"/api/cases/{case['id']}/exports", json={"recording_id": recording_id}
    ).json()
    assert first["id"] == second["id"]
    assert first["manifest_sha256"] == second["manifest_sha256"]

    bytes1 = real_client.get(f"/api/exports/{first['id']}/file").content
    bytes2 = real_client.get(f"/api/exports/{second['id']}/file").content
    assert bytes1 == bytes2


def test_export_requires_examiner_or_admin(
    real_reviewer_client: TestClient, tmp_path: Path, real_evidence_dir: Path
) -> None:
    resp = real_reviewer_client.post(
        "/api/cases/does-not-matter/exports", json={"channel": 0}
    )
    assert resp.status_code == 403
