"""Real scan pipeline, recordings/frames/hex/thumb/clips endpoints (task
B2, docs/02-BACKEND.md §6/§12).

Acceptance: "pipeline e2e, resumability, prove-it and streaming tests ...
Fast tests with fake registered parsers prove the pipeline, resumability,
hex annotations + live hash, and Range streaming." ``pramaan_formats`` /
``pramaan_recovery`` (task C2) don't exist yet, so this file registers a
small fake ``VendorParser`` + fingerprinter through
``pramaan_worker.registry`` instead — the same registry the real parsers
plug into once C2 lands (see docs/progress/B2.md "Integration contract").

The "evidence image" here is a real, ffmpeg-decodable two-GOP H.264 Annex-B
stream (baseline profile, one keyframe per GOP) embedded at a fixed offset
inside an otherwise-arbitrary byte buffer — real enough that the clip and
thumbnail stages genuinely stream-copy/decode it with ffmpeg, not just push
opaque bytes around.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pramaan_api.settings import Settings
from pramaan_core.evidence import EvidenceReader
from pramaan_core.ids import content_id
from pramaan_core.ids import frame_id as core_frame_id
from pramaan_core.models import ByteRange, FrameRef, Recording, VendorMatch
from pramaan_worker import registry

FFMPEG_TIMEOUT_S = 30
PAD = 128  # arbitrary filler either side of the embedded elementary stream


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True, timeout=5)
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not available")


def _nal_boundaries(data: bytes) -> list[tuple[int, int]]:
    """``[(offset, start_code_len), ...]`` for every Annex-B start code in
    ``data``, in order (a 4-byte start code's 3-byte suffix is not double
    counted)."""
    offs: list[tuple[int, int]] = []
    for m in re.finditer(rb"\x00\x00\x01", data):
        i = m.start()
        if i >= 1 and data[i - 1] == 0:
            offs.append((i - 1, 4))
        else:
            offs.append((i, 3))
    return offs


def _build_two_gop_h264(tmp_path: Path) -> bytes:
    """A tiny, real, all-keyframe H.264 Annex-B stream: two 1-frame GOPs
    (baseline profile, ``-g 1`` forces a fresh SPS/PPS/IDR per frame so
    each chunk below is independently decodable)."""
    out = tmp_path / "gop.h264"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=size=64x64:rate=2:color=red",
            "-frames:v",
            "2",
            "-c:v",
            "libx264",
            "-profile:v",
            "baseline",
            "-g",
            "1",
            "-f",
            "h264",
            str(out),
        ],
        check=True,
        capture_output=True,
        timeout=FFMPEG_TIMEOUT_S,
    )
    return out.read_bytes()


def _frame_chunks(data: bytes) -> list[tuple[int, int]]:
    """``[(payload_offset, payload_len), ...]`` relative to ``data``, one
    per GOP (each run of NALs starting at an SPS, up to the next SPS or
    EOF). ``payload_offset`` is the position of the GOP's own leading start
    code: a real vendor parser's/carver's ``FrameRef.payload_offset``
    points at the access unit's raw elementary-stream bytes, start
    code(s) included (``pramaan_formats.hiksim.iter_frames``,
    ``pramaan_recovery.carve.to_frame_refs`` — see docs/progress/B2.md
    "Integration contract"), which is what makes each payload chunk here
    independently concatenable into a valid Annex-B stream with no bytes
    re-added.
    """
    boundaries = _nal_boundaries(data)
    sps_starts = [off for off, sc_len in boundaries if data[off + sc_len] & 0x1F == 7]
    sps_starts.append(len(data))
    return [(sps_starts[i], sps_starts[i + 1] - sps_starts[i]) for i in range(len(sps_starts) - 1)]


class FakeVendorParser:
    """A minimal ``pramaan_formats.base.VendorParser`` (docs/01-FORENSIC-
    CORE.md §4.5) built entirely in-test — registered through
    ``pramaan_worker.registry`` in place of a real one.
    """

    family = "testvendor"

    def __init__(self, recording: Recording, frames: list[FrameRef]) -> None:
        self._recording = recording
        self._frames = frames

    def detect(self, reader: EvidenceReader) -> VendorMatch | None:
        return _fake_vendor_match()

    def list_recordings(self, reader: EvidenceReader) -> list[Recording]:
        return [self._recording]

    def iter_frames(self, reader: EvidenceReader, rec: Recording) -> list[FrameRef]:
        return list(self._frames)

    def unindexed_ranges(self, reader: EvidenceReader) -> list[ByteRange]:
        return []

    def index_state(self, reader: EvidenceReader) -> dict[str, Any]:
        return {"family": self.family}


def _build_fake_image(tmp_path: Path, image_path: Path) -> list[dict[str, Any]]:
    """Write a crafted evidence image to ``image_path`` and return the raw
    per-frame specs (offsets/lengths/hash) a real vendor parser would have
    found in it. ``_finalise`` turns these into ``FrameRef``/``Recording``
    once the real (content-derived) evidence id is known.
    """
    h264 = _build_two_gop_h264(tmp_path)
    chunks = _frame_chunks(h264)
    assert len(chunks) == 2, f"expected 2 GOPs, got {len(chunks)}"

    image_bytes = (b"\x00" * PAD) + h264 + (b"\xff" * PAD)
    image_path.write_bytes(image_bytes)

    frame_specs = []
    for rel_offset, rel_len in chunks:
        payload_offset = PAD + rel_offset
        payload = image_bytes[payload_offset : payload_offset + rel_len]
        frame_specs.append(
            {
                # A few bytes of the filler just before the payload stand
                # in for a vendor frame header, purely so the hex-view
                # "vendor_header"/"start_code" annotations have something
                # to show (this synthetic format has no real header).
                "header_offset": max(payload_offset - 8, 0),
                "payload_offset": payload_offset,
                "payload_len": rel_len,
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return frame_specs


def _finalise(image_id: str, frame_specs: list[dict[str, Any]]) -> tuple[Recording, list[FrameRef]]:
    recording_id = content_id("rec", {"image_id": image_id, "channel": 0, "start": 0})
    frames = [
        FrameRef(
            # task FIX-3: frame_id is derived from (image_id, header_offset,
            # payload_sha256), no longer a bare truncated payload hash —
            # see pramaan_core.ids.frame_id.
            frame_id=core_frame_id(image_id, spec["header_offset"], spec["payload_sha256"]),
            image_id=image_id,
            channel=0,
            stream="main",
            codec="h264",
            frame_type="I",
            header_offset=spec["header_offset"],
            payload_offset=spec["payload_offset"],
            payload_len=spec["payload_len"],
            ts_header_us=i * 500_000,
            ts_index_us=i * 500_000,
            width=64,
            height=64,
            source="index",
            recording_id=recording_id,
            deleted=False,
            payload_sha256=spec["payload_sha256"],
        )
        for i, spec in enumerate(frame_specs)
    ]
    span_start = frames[0].payload_offset
    span_end = frames[-1].payload_offset + frames[-1].payload_len
    recording = Recording(
        id=recording_id,
        image_id=image_id,
        channel=0,
        stream="main",
        start_ts_us=0,
        end_ts_us=500_000,
        byte_ranges=[ByteRange(offset=span_start, length=span_end - span_start)],
        source="index",
        deleted=False,
    )
    return recording, frames


@pytest.fixture(autouse=True)
def _reset_registry_around_test() -> Iterator[None]:
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


def _intake_body() -> dict[str, str]:
    return {
        "seized_at_local": "2026-03-12T16:40:00+05:30",
        "dvr_displayed_time": "2026-03-12T16:45:12",
        "reference_time": "2026-03-12T16:40:00+05:30",
        "reference_source": "NTP phone clock",
        "timezone": "Asia/Kolkata",
        "make_model_label": "Test Vendor DVR (fake)",
        "notes": "fixture for test_pipeline_real",
    }


def _create_case(client: TestClient, number: str) -> dict[str, Any]:
    resp = client.post("/api/cases", json={"case_number": number, "title": f"Fake DVR {number}"})
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _register_and_scan(
    client: TestClient, tmp_path: Path, real_evidence_dir: Path, case_number: str
) -> tuple[dict[str, Any], dict[str, Any], list[FrameRef]]:
    """Full setup: crafted image -> register evidence -> register fake
    parser (now that the real content-derived ``image_id`` is known) ->
    run a full scan job. Returns ``(case, job, frames)``.
    """
    case = _create_case(client, case_number)
    image_path = real_evidence_dir / f"{case_number}.img"
    frame_specs = _build_fake_image(tmp_path, image_path)

    ev_resp = client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(image_path), "label": "fake disk", "intake": _intake_body()},
    )
    assert ev_resp.status_code == 201, ev_resp.text
    image = ev_resp.json()

    recording, frames = _finalise(image["id"], frame_specs)
    registry.register_fingerprinter(lambda reader: [_fake_vendor_match()])
    registry.register_vendor_parser(FakeVendorParser(recording, frames))

    scan_resp = client.post(f"/api/evidence/{image['id']}/scan", json={})
    assert scan_resp.status_code == 202, scan_resp.text
    job = scan_resp.json()
    return case, job, frames


def _fake_vendor_match() -> VendorMatch:
    return VendorMatch(
        family="testvendor",
        display_name="Test Vendor (fake, in-test)",
        platform=None,
        tier="A",
        confidence=0.95,
        evidence=["fake signature for test_pipeline_real"],
        model=None,
        serial=None,
        fs_version=None,
    )


def test_scan_pipeline_runs_all_stages_with_fake_parser(
    real_client: TestClient, tmp_path: Path, real_evidence_dir: Path
) -> None:
    case, job, frames = _register_and_scan(
        real_client, tmp_path, real_evidence_dir, "CR-B2-0001"
    )
    assert job["status"] == "done", job
    assert len(job["stages"]) == 11
    by_name = {s["name"]: s for s in job["stages"]}
    assert by_name["hash_verify"]["status"] == "done"
    assert by_name["fingerprint"]["status"] == "done"
    assert "vendor match" in by_name["fingerprint"]["message"]
    assert by_name["parse_index"]["status"] == "done"
    assert "2 frame(s)" in by_name["parse_index"]["message"]
    # No Tier-A gap once parse_index found a match — infer_layout/carve
    # have nothing forced on them, but must still report ok (skipped is
    # fine either way depending on registry state).
    assert by_name["infer_layout"]["status"] == "done"
    assert by_name["frame_index"]["status"] == "done"
    assert "2 frame(s)" in by_name["frame_index"]["message"]
    assert by_name["clips"]["status"] == "done"
    assert "1 clip(s)" in by_name["clips"]["message"]

    recordings = real_client.get(f"/api/cases/{case['id']}/recordings").json()
    assert len(recordings) == 1
    recording_id = recordings[0]["id"]

    got = real_client.get(f"/api/recordings/{recording_id}").json()
    assert got["id"] == recording_id

    frame_rows = real_client.get(f"/api/cases/{case['id']}/frames").json()
    assert len(frame_rows) == 2
    assert {f["frame_id"] for f in frame_rows} == {f.frame_id for f in frames}

    frame_detail = real_client.get(f"/api/frames/{frames[0].frame_id}").json()
    assert frame_detail["frame_id"] == frames[0].frame_id


def test_prove_it_hex_recomputes_matching_payload_hash(
    real_client: TestClient, tmp_path: Path, real_evidence_dir: Path
) -> None:
    case, job, frames = _register_and_scan(
        real_client, tmp_path, real_evidence_dir, "CR-B2-0002"
    )
    assert job["status"] == "done", job

    for frame in frames:
        resp = real_client.get(
            f"/api/frames/{frame.frame_id}/hex", params={"before": 16, "after": 16}
        )
        assert resp.status_code == 200, resp.text
        view = resp.json()
        assert view["payload_sha256_stored"] == frame.payload_sha256
        assert view["payload_sha256_recomputed"] == frame.payload_sha256
        assert view["matches"] is True
        names = {a["name"] for a in view["annotations"]}
        assert "payload" in names


def test_prove_it_hex_flags_tamper_as_not_matching(
    real_client: TestClient, tmp_path: Path, real_evidence_dir: Path
) -> None:
    case, job, frames = _register_and_scan(
        real_client, tmp_path, real_evidence_dir, "CR-B2-0003"
    )
    assert job["status"] == "done", job

    # Flip a byte inside the second frame's payload, directly on disk —
    # bypassing the pipeline entirely — then re-request its hex view: the
    # live recompute must now disagree with the stored payload_sha256 claim.
    image = real_client.get(f"/api/evidence/{frames[1].image_id}").json()
    path = Path(image["path"])
    data = bytearray(path.read_bytes())
    tamper_at = frames[1].payload_offset + 2
    data[tamper_at] ^= 0xFF
    path.write_bytes(bytes(data))

    resp = real_client.get(f"/api/frames/{frames[1].frame_id}/hex")
    assert resp.status_code == 200
    view = resp.json()
    assert view["matches"] is False
    assert not view["payload_sha256_recomputed"].startswith(view["payload_sha256_stored"])


def test_frame_thumbnail_is_a_real_derived_jpeg(
    real_client: TestClient, tmp_path: Path, real_evidence_dir: Path
) -> None:
    case, job, frames = _register_and_scan(
        real_client, tmp_path, real_evidence_dir, "CR-B2-0004"
    )
    assert job["status"] == "done", job

    resp = real_client.get(f"/api/frames/{frames[0].frame_id}/thumb")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers.get("x-pramaan-derived") == "true"
    assert resp.content[:2] == b"\xff\xd8"  # JPEG SOI marker — a real decode, not a stub


def test_clip_stream_range_over_real_stream_copied_mp4(
    real_client: TestClient, real_settings: Settings, tmp_path: Path, real_evidence_dir: Path
) -> None:
    case, job, frames = _register_and_scan(
        real_client, tmp_path, real_evidence_dir, "CR-B2-0005"
    )
    assert job["status"] == "done", job

    # Recover the clip id straight from the case's own case.db (there is no
    # list-clips endpoint; this is test-only introspection).
    from pramaan_api.real.paths import case_dir as real_case_dir

    conn = sqlite3.connect(str(real_case_dir(real_settings.data_dir, case["id"]) / "case.db"))
    conn.row_factory = sqlite3.Row
    clip_row = conn.execute("SELECT * FROM clips").fetchone()
    conn.close()
    assert clip_row is not None, "clips stage should have produced exactly one clip"
    clip_id = clip_row["id"]
    assert Path(clip_row["path"]).is_file()

    full = real_client.get(f"/api/clips/{clip_id}/stream")
    assert full.status_code == 200
    assert full.headers["accept-ranges"] == "bytes"
    total = int(full.headers["content-length"])
    assert total > 0
    assert full.content[4:8] in (b"ftyp",)

    ranged = real_client.get(f"/api/clips/{clip_id}/stream", headers={"Range": "bytes=0-7"})
    assert ranged.status_code == 206
    assert ranged.headers["content-range"] == f"bytes 0-7/{total}"
    assert ranged.content == full.content[:8]


def test_resumability_second_scan_skips_completed_stages(
    real_client: TestClient, tmp_path: Path, real_evidence_dir: Path
) -> None:
    case, job, frames = _register_and_scan(
        real_client, tmp_path, real_evidence_dir, "CR-B2-0006"
    )
    assert job["status"] == "done", job
    image_id = frames[0].image_id

    # Re-run the scan for the *same* evidence (same sha256 -> same
    # input_hash): every stage must be skipped via its marker file, not
    # re-executed (docs/02-BACKEND.md §6/§12 "resumability").
    resp = real_client.post(f"/api/evidence/{image_id}/scan", json={})
    assert resp.status_code == 202, resp.text
    second_job = resp.json()
    assert second_job["status"] == "done"
    for stage in second_job["stages"]:
        assert "already done for this input" in (stage["message"] or ""), stage

    # And the data it (didn't) redo is still there and unchanged.
    recordings = real_client.get(f"/api/cases/{case['id']}/recordings").json()
    assert len(recordings) == 1
    frame_rows = real_client.get(f"/api/cases/{case['id']}/frames").json()
    assert len(frame_rows) == 2


def test_scan_degrades_gracefully_on_plain_bytes_with_no_matching_family(
    real_client: TestClient, real_evidence_dir: Path
) -> None:
    """Plain non-DVR bytes: no family fingerprints above the Tier-A
    threshold, so ``parse_index`` has no family to key off of and reports
    ``skipped``. C3's slice of the pipeline (``pramaan_recovery.infer``,
    ``pramaan_recovery.deletion``, ``pramaan_logs.parse_logs``) has landed
    and runs for real against these bytes: ``infer_layout`` finds no
    consistent header/magic in random bytes (correctly reports "no layout
    could be inferred", not "parser unavailable"), and ``logs``/
    ``deletion_verdict`` correctly find zero events/findings. The job must
    still finish ``done`` (docs/PROMPTBOOK.md: "a missing package degrades
    gracefully" — the same principle, extended to "a stage that legitimately
    finds nothing also degrades gracefully"), never fail the pipeline.
    ``fingerprint`` and ``carve`` (task C2) run for real too and correctly
    find nothing.

    The degrade-gracefully-on-a-missing-registry-entry path (the original
    intent of this test, before C3 landed real ``infer_layout``/``logs``/
    ``deletion_verdict`` implementations) is covered separately by
    ``test_scan_degrades_gracefully_when_a_stage_parser_is_unregistered``
    below, which forces each of those three lookups to miss via
    ``pramaan_worker.registry``'s test-override hooks rather than relying on
    the real packages being absent.
    """
    case = _create_case(real_client, "CR-B2-0007")
    file_path = real_evidence_dir / "plain.raw"
    file_path.write_bytes(bytes((i * 7 + 3) % 256 for i in range(4096)))

    ev = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(file_path), "label": "plain disk", "intake": _intake_body()},
    ).json()

    resp = real_client.post(f"/api/evidence/{ev['id']}/scan", json={})
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "done", job
    by_name = {s["name"]: s for s in job["stages"]}
    assert all(s["status"] == "done" for s in job["stages"]), job["stages"]
    assert by_name["parse_index"]["message"].startswith("parse_index: skipped")
    assert by_name["infer_layout"]["message"] == "infer_layout: no layout could be inferred"
    assert by_name["logs"]["message"] == "logs: 0 event(s) via unknown"
    assert by_name["deletion_verdict"]["message"] == "deletion_verdict: 0 finding(s)"
    # frame_index always runs (core-only) and writes an empty index, since
    # nothing above found any frames in plain non-DVR bytes.
    assert "0 frame(s)" in by_name["frame_index"]["message"]

    frame_rows = real_client.get(f"/api/cases/{case['id']}/frames").json()
    assert frame_rows == []
    recordings = real_client.get(f"/api/cases/{case['id']}/recordings").json()
    assert recordings == []
    log_events = real_client.get(f"/api/cases/{case['id']}/log-events").json()
    assert log_events == []
    deletions = real_client.get(f"/api/cases/{case['id']}/deletions").json()
    assert deletions == []


def test_scan_degrades_gracefully_when_a_stage_parser_is_unregistered(
    real_client: TestClient, real_evidence_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same shape as the original (pre-C3) version of the test above, kept
    meaningful now that the real packages exist: force
    ``infer_layout``/``logs``/``deletion_verdict``'s *registry lookups*
    (not their bodies) to miss, exactly as a genuine ``ImportError`` would
    (``pramaan_worker.registry.get_layout_inferrer``/``get_log_parser``/
    ``get_deletion_analyzer`` all return ``None``). The pipeline must still
    finish every stage ``done`` with an honest "parser unavailable" message
    and never fail the job over a dependency that isn't there
    (docs/PROMPTBOOK.md: "a missing package degrades gracefully").
    """
    monkeypatch.setattr(registry, "get_layout_inferrer", lambda: None)
    monkeypatch.setattr(registry, "get_log_parser", lambda: None)
    monkeypatch.setattr(registry, "get_deletion_analyzer", lambda: None)

    case = _create_case(real_client, "CR-B2-0008")
    file_path = real_evidence_dir / "plain2.raw"
    file_path.write_bytes(bytes((i * 11 + 5) % 256 for i in range(4096)))
    ev = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(file_path), "label": "plain disk", "intake": _intake_body()},
    ).json()

    resp = real_client.post(f"/api/evidence/{ev['id']}/scan", json={})
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "done", job
    by_name = {s["name"]: s for s in job["stages"]}
    assert all(s["status"] == "done" for s in job["stages"]), job["stages"]
    for stage_name in ("infer_layout", "logs", "deletion_verdict"):
        assert "parser unavailable" in by_name[stage_name]["message"], by_name[stage_name]

    frame_rows = real_client.get(f"/api/cases/{case['id']}/frames").json()
    assert frame_rows == []
    recordings = real_client.get(f"/api/cases/{case['id']}/recordings").json()
    assert recordings == []
    log_events = real_client.get(f"/api/cases/{case['id']}/log-events").json()
    assert log_events == []
    deletions = real_client.get(f"/api/cases/{case['id']}/deletions").json()
    assert deletions == []


def test_confirm_inferred_layout_twice_is_idempotent_not_a_500(
    real_client: TestClient,
    tmp_path: Path,
    real_evidence_dir: Path,
    real_settings: Settings,
) -> None:
    """Task FIX-4 (repro in docs/progress/FIX-2.md "Cross-workstream
    issues" #2): a *second* ``POST /inferred-layouts/{lid}/confirm`` of the
    same layout used to raise ``sqlite3.IntegrityError: FOREIGN KEY
    constraint failed`` — the first confirm's ``clips`` stage stream-copies
    a real MP4 and inserts a ``clips`` row referencing the ``recordings``
    the reindex's ``DELETE FROM recordings ... AND source = 'inferred'``
    then tries to remove and re-insert on the second confirm. Needs a real,
    ffmpeg-decodable payload (this module's two-GOP fixture) so the
    ``clips`` stage actually inserts a row instead of catching a remux
    failure per-recording and inserting nothing. A re-confirm must now be a
    genuine no-op: same ``confirmed_by``, same recordings, one
    ``layout.confirmed`` audit entry (not two) plus one
    ``layout.confirm_noop``, never a 500.
    """
    from pramaan_api.real import appdb

    case = _create_case(real_client, "CR-FIX4-RECONFIRM")
    image_path = real_evidence_dir / "xsim_fake.img"
    frame_specs = _build_fake_image(tmp_path, image_path)

    ev_resp = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(image_path), "label": "fake xsim disk", "intake": _intake_body()},
    )
    assert ev_resp.status_code == 201, ev_resp.text
    image = ev_resp.json()

    _recording, frames = _finalise(image["id"], frame_specs)

    class _FakeInferredParser:
        def iter_frames(self, reader: Any, image_id: str) -> list[FrameRef]:
            return list(frames)

    registry.register_inferred_parser_factory(lambda layout: _FakeInferredParser())

    layout_id = content_id("layout", {"image_id": image["id"]})
    guarded = appdb.case_db(real_settings.data_dir, case["id"])
    with guarded.lock:
        guarded.conn.execute(
            "INSERT INTO inferred_layouts (id, image_id, header_len, magic, fields, codec,"
            " confirmed_by) VALUES (?,?,?,?,?,?,?)",
            (layout_id, image["id"], 8, None, "[]", "h264", None),
        )
        guarded.conn.commit()

    confirm1 = real_client.post(f"/api/inferred-layouts/{layout_id}/confirm")
    assert confirm1.status_code == 200, confirm1.text
    assert confirm1.json()["confirmed_by"] == "examiner"

    recordings_after_first = real_client.get(f"/api/cases/{case['id']}/recordings").json()
    assert len(recordings_after_first) > 0

    confirm2 = real_client.post(f"/api/inferred-layouts/{layout_id}/confirm")
    assert confirm2.status_code == 200, confirm2.text
    assert confirm2.json()["confirmed_by"] == "examiner"

    recordings_after_second = real_client.get(f"/api/cases/{case['id']}/recordings").json()
    assert {r["id"] for r in recordings_after_second} == {
        r["id"] for r in recordings_after_first
    }
    assert len(recordings_after_second) == len(recordings_after_first)

    audit = real_client.get(f"/api/cases/{case['id']}/audit").json()
    actions = [e["action"] for e in audit["items"]]
    assert actions.count("layout.confirmed") == 1
    assert actions.count("layout.confirm_noop") == 1


def test_confirm_reruns_every_downstream_stage_once_via_fake_registered_stages(
    real_client: TestClient,
    tmp_path: Path,
    real_evidence_dir: Path,
    real_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task FIX-12 (repro: docs/progress/FIX-11.md "Cross-workstream
    issues" #1 — confirming a Tier B layout never re-ran ``deletion_verdict``,
    so ``GET /cases/{cid}/deletions`` stayed whatever it was computed as
    during the automatic ``/scan``, empty for any Tier B image at that
    point). Confirming must now re-run *every* stage downstream of parsing
    that depends on ``recordings``/frames — ``frame_index``, ``logs``,
    ``deletion_verdict``, ``clips``, and the AI-registered ``timeline``/
    ``motion`` stages — in pipeline order, exactly once per confirm.

    ``logs``/``deletion_verdict`` are swapped for small call-counting fakes
    through ``pramaan_worker.registry`` (the same hook the rest of this file
    uses). ``timeline``/``motion`` are AI-owned and reached only through
    ``pramaan_worker.stages.default_stages()`` (docs/03-AI-TIMELINE.md's own
    ``register_stage`` hook) — this test monkeypatches that one function for
    its own duration (auto-reverted by ``monkeypatch``, never touching the
    real ``timeline``/``motion`` stages other tests in this process rely on)
    rather than calling ``pramaan_worker.stages.register_stage`` directly,
    which would permanently clobber the real AI registrations for the rest
    of the test session (module-level ``register_stage`` calls in
    ``apps/api/pramaan_api/routers/{timeline,analytics}.py`` only run once,
    at first import).
    """
    from pramaan_api.real import appdb
    from pramaan_core.models import DeletionFinding, LogEvent
    from pramaan_worker import stages as stages_module
    from pramaan_worker.runner import StageContext, StageResult

    case = _create_case(real_client, "CR-FIX12-DOWNSTREAM")
    image_path = real_evidence_dir / "xsim_fake_downstream.img"
    frame_specs = _build_fake_image(tmp_path, image_path)

    ev_resp = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(image_path), "label": "fake xsim disk", "intake": _intake_body()},
    )
    assert ev_resp.status_code == 201, ev_resp.text
    image = ev_resp.json()

    _recording, frames = _finalise(image["id"], frame_specs)

    class _FakeInferredParser:
        def iter_frames(self, reader: Any, image_id: str) -> list[FrameRef]:
            return list(frames)

    registry.register_inferred_parser_factory(lambda layout: _FakeInferredParser())

    calls = {"logs": 0, "deletion_verdict": 0, "timeline": 0, "motion": 0}

    def fake_log_parser(reader: Any, family: str) -> list[LogEvent]:
        calls["logs"] += 1
        return []

    def fake_deletion_analyzer(
        *,
        image_id: str,
        recordings: list[Recording],
        frames: list[FrameRef],
        log_events: list[LogEvent],
    ) -> list[DeletionFinding]:
        calls["deletion_verdict"] += 1
        # The whole point of FIX-12: by the time this runs, confirm's own
        # parse_inferred_layout must already have populated `recordings` —
        # the pre-FIX-12 bug ran deletion_verdict against whatever the
        # automatic /scan had (empty, for a Tier B image at that point).
        assert recordings, "deletion analyzer must see the confirm-populated recordings"
        return [
            DeletionFinding(
                id=content_id("del", {"image_id": image_id, "n": calls["deletion_verdict"]}),
                image_id=image_id,
                channel=0,
                start_ts_us=0,
                end_ts_us=100_000,
                method="format",
                actor=None,
                action_ts_us=None,
                frames_recovered=1,
                bytes_recovered=1,
                confidence=0.9,
                reasons=["fake finding for test_pipeline_real"],
                evidence_refs=[],
            )
        ]

    registry.register_log_parser(fake_log_parser)
    registry.register_deletion_analyzer(fake_deletion_analyzer)

    real_default_stages = stages_module.default_stages

    def fake_timeline(ctx: StageContext) -> StageResult:
        calls["timeline"] += 1
        return StageResult(
            stage="timeline",
            ok=True,
            input_hash=ctx.input_hash,
            output_hash=None,
            message="timeline: fake",
        )

    def fake_motion(ctx: StageContext) -> StageResult:
        calls["motion"] += 1
        return StageResult(
            stage="motion",
            ok=True,
            input_hash=ctx.input_hash,
            output_hash=None,
            message="motion: fake",
        )

    def fake_default_stages() -> dict[str, Any]:
        base = dict(real_default_stages())
        base["timeline"] = fake_timeline
        base["motion"] = fake_motion
        return base

    monkeypatch.setattr(stages_module, "default_stages", fake_default_stages)

    layout_id = content_id("layout", {"image_id": image["id"]})
    guarded = appdb.case_db(real_settings.data_dir, case["id"])
    with guarded.lock:
        guarded.conn.execute(
            "INSERT INTO inferred_layouts (id, image_id, header_len, magic, fields, codec,"
            " confirmed_by) VALUES (?,?,?,?,?,?,?)",
            (layout_id, image["id"], 8, None, "[]", "h264", None),
        )
        guarded.conn.commit()

    confirm = real_client.post(f"/api/inferred-layouts/{layout_id}/confirm")
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["confirmed_by"] == "examiner"

    assert calls == {"logs": 1, "deletion_verdict": 1, "timeline": 1, "motion": 1}, calls

    deletions = real_client.get(f"/api/cases/{case['id']}/deletions").json()
    assert len(deletions) == 1
    assert deletions[0]["method"] == "format"

    audit = real_client.get(f"/api/cases/{case['id']}/audit").json()
    actions = [e["action"] for e in audit["items"]]
    for stage_name in (
        "pipeline.frame_index",
        "pipeline.logs",
        "pipeline.deletion_verdict",
        "pipeline.clips",
        "pipeline.timeline",
        "pipeline.motion",
    ):
        assert actions.count(stage_name) == 1, (stage_name, actions)

    # A second confirm of the *same* layout must stay the FIX-4 idempotent
    # no-op path (no re-run of the reindex at all) — the downstream stages
    # must not run a second time, and no duplicate deletion finding appears.
    confirm2 = real_client.post(f"/api/inferred-layouts/{layout_id}/confirm")
    assert confirm2.status_code == 200, confirm2.text
    assert calls == {"logs": 1, "deletion_verdict": 1, "timeline": 1, "motion": 1}, calls
    deletions_after_second = real_client.get(f"/api/cases/{case['id']}/deletions").json()
    assert len(deletions_after_second) == 1
