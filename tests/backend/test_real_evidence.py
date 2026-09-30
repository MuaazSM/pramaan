"""Real (non-fixture) mode: cases, evidence registration, jobs, custody
(task B1, docs/02-BACKEND.md §5-8, §12).

Acceptance (02 §12 / docs/PROMPTBOOK.md B1): "registering a generated file
hashes it and appends audit entries visible via /audit."
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient


def _intake_body() -> dict[str, str]:
    return {
        "seized_at_local": "2026-03-12T16:40:00+05:30",
        "dvr_displayed_time": "2026-03-12T16:45:12",
        "reference_time": "2026-03-12T16:40:00+05:30",
        "reference_source": "NTP phone clock",
        "timezone": "Asia/Kolkata",
        "make_model_label": "Hikvision DS-7208 (synthetic)",
        "notes": "Device time not changed",
    }


def _make_evidence_file(evidence_dir: Path, name: str = "device.raw", size: int = 65536) -> Path:
    path = evidence_dir / name
    data = bytes((i * 7 + 3) % 256 for i in range(size))
    path.write_bytes(data)
    return path


def _create_case(client: TestClient, number: str) -> dict:
    resp = client.post(
        "/api/cases", json={"case_number": number, "title": f"Real-mode case {number}"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_and_list_case_real_mode(real_client: TestClient) -> None:
    case = _create_case(real_client, "CR-REAL-0001")
    assert case["case_number"] == "CR-REAL-0001"
    assert case["status"] == "open"

    listed = real_client.get("/api/cases").json()
    assert any(c["id"] == case["id"] for c in listed)

    fetched = real_client.get(f"/api/cases/{case['id']}").json()
    assert fetched == case

    patched = real_client.patch(f"/api/cases/{case['id']}", json={"status": "closed"}).json()
    assert patched["status"] == "closed"


def test_register_evidence_hashes_real_file_and_appends_audit(
    real_client: TestClient, real_evidence_dir: Path
) -> None:
    case = _create_case(real_client, "CR-REAL-0002")
    file_path = _make_evidence_file(real_evidence_dir)
    expected_sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()

    resp = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(file_path), "label": "Test drive", "intake": _intake_body()},
    )
    assert resp.status_code == 201, resp.text
    image = resp.json()
    assert image["sha256"] == expected_sha256
    assert image["format"] == "raw"
    assert image["verified"] is True
    assert image["size_bytes"] == file_path.stat().st_size

    fetched = real_client.get(f"/api/evidence/{image['id']}").json()
    assert fetched == image

    listed = real_client.get(f"/api/cases/{case['id']}/evidence").json()
    assert any(e["id"] == image["id"] for e in listed)

    # audit entries visible via /audit (docs/02-BACKEND.md §8/§12)
    audit = real_client.get(f"/api/cases/{case['id']}/audit").json()
    actions = [e["action"] for e in audit["items"]]
    assert "case.created" in actions
    assert "evidence.registered" in actions
    registered_entry = next(e for e in audit["items"] if e["action"] == "evidence.registered")
    assert registered_entry["payload_sha256"] == expected_sha256
    assert registered_entry["object_id"] == image["id"]
    assert registered_entry["actor"] == "examiner"
    assert registered_entry["signature"]

    # chain verifies end to end (hash links + Ed25519 signatures)
    verify = real_client.get(f"/api/cases/{case['id']}/audit/verify").json()
    assert verify["ok"] is True
    assert verify["first_bad_seq"] is None
    assert verify["length"] == len(audit["items"])


def test_registering_same_bytes_twice_is_idempotent(
    real_client: TestClient, real_evidence_dir: Path
) -> None:
    case = _create_case(real_client, "CR-REAL-0003")
    file_path = _make_evidence_file(real_evidence_dir, "dup.raw")

    first = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(file_path), "label": "first", "intake": _intake_body()},
    ).json()
    second = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(file_path), "label": "second", "intake": _intake_body()},
    ).json()
    assert first["id"] == second["id"]  # content-derived id — same bytes, same id


def test_verify_job_rehashes_and_updates_evidence(
    real_client: TestClient, real_evidence_dir: Path
) -> None:
    case = _create_case(real_client, "CR-REAL-0004")
    file_path = _make_evidence_file(real_evidence_dir, "verify.raw")
    image = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(file_path), "label": "x", "intake": _intake_body()},
    ).json()

    resp = real_client.post(f"/api/evidence/{image['id']}/verify")
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["kind"] == "verify"
    assert job["status"] == "done"
    assert len(job["stages"]) == 1
    assert job["stages"][0]["name"] == "hash_verify"
    assert job["stages"][0]["status"] == "done"
    assert job["stages"][0]["pct"] == 100.0
    assert image["sha256"] in job["stages"][0]["message"]

    fetched_job = real_client.get(f"/api/jobs/{job['id']}").json()
    assert fetched_job["status"] == "done"

    fetched_image = real_client.get(f"/api/evidence/{image['id']}").json()
    assert fetched_image["verified"] is True

    audit = real_client.get(f"/api/cases/{case['id']}/audit").json()
    actions = [e["action"] for e in audit["items"]]
    assert "pipeline.hash_verify" in actions


def test_scan_job_runs_every_stage(real_client: TestClient, real_evidence_dir: Path) -> None:
    case = _create_case(real_client, "CR-REAL-0005")
    file_path = _make_evidence_file(real_evidence_dir, "scan.raw")
    image = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(file_path), "label": "x", "intake": _intake_body()},
    ).json()

    resp = real_client.post(f"/api/evidence/{image['id']}/scan", json={})
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["kind"] == "scan"
    assert job["status"] == "done"
    assert len(job["stages"]) == 11
    assert all(s["status"] == "done" for s in job["stages"])
    assert job["stages"][0]["name"] == "hash_verify"


def test_reviewer_cannot_register_evidence(
    real_client: TestClient, real_reviewer_client: TestClient, real_evidence_dir: Path
) -> None:
    case = _create_case(real_client, "CR-REAL-0006")
    resp = real_reviewer_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={
            "path": str(real_evidence_dir / "whatever.raw"),
            "label": "x",
            "intake": _intake_body(),
        },
    )
    assert resp.status_code == 403


def test_evidence_registration_outside_evidence_roots_rejected(
    real_client: TestClient, tmp_path: Path
) -> None:
    case = _create_case(real_client, "CR-REAL-0007")
    outside = tmp_path / "outside.raw"
    outside.write_bytes(b"not evidence")
    resp = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(outside), "label": "x", "intake": _intake_body()},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_evidence_registration_traversal_rejected(
    real_client: TestClient, real_evidence_dir: Path
) -> None:
    case = _create_case(real_client, "CR-REAL-0008")
    traversal_path = str(real_evidence_dir / ".." / "escape.raw")
    resp = real_client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": traversal_path, "label": "x", "intake": _intake_body()},
    )
    assert resp.status_code == 400


def test_fs_browse_real_mode_within_and_outside_root(
    real_client: TestClient, real_evidence_dir: Path, tmp_path: Path
) -> None:
    (real_evidence_dir / "a.raw").write_bytes(b"x")
    (real_evidence_dir / "sub").mkdir()

    within = real_client.get("/api/fs/browse", params={"path": str(real_evidence_dir)})
    assert within.status_code == 200
    names = {e["name"] for e in within.json()}
    assert {"a.raw", "sub"} <= names

    outside = real_client.get("/api/fs/browse", params={"path": str(tmp_path)})
    assert outside.status_code == 200
    assert outside.json() == []


def test_missing_csrf_header_rejected(real_settings, real_evidence_dir: Path) -> None:
    from pramaan_api.deps import get_settings
    from pramaan_api.main import app

    def _settings():
        return real_settings

    app.dependency_overrides[get_settings] = _settings
    try:
        with TestClient(app) as client:
            resp = client.post("/api/auth/login", json={"username": "examiner", "password": "demo"})
            assert resp.status_code == 200
            # Deliberately not echoing the CSRF cookie in a header.
            create = client.post("/api/cases", json={"case_number": "CR-REAL-0009", "title": "x"})
            assert create.status_code == 403
            assert create.json()["error"]["code"] == "csrf_failed"
    finally:
        app.dependency_overrides.pop(get_settings, None)


# --- FIX-4 bug 1: frame reads tolerate a pre-FIX-3 Parquet schema ----------
#
# `list_frames`/`count_frames` used to hard-select `payload_sha256` (a
# FIX-3 addition) from the frame-index Parquet, 500ing (DuckDB
# `BinderException`) on any frames-*.parquet written before that column
# existed. See docs/progress/F4.md "Cross-workstream issues" #1 for the
# real-mode repro (`POST /cases/{cid}/exports` 500ing on `list_frames`).


def _old_schema_frame_row(*, frame_id: str, image_id: str, recording_id: str) -> dict:
    """A frame row using only pre-FIX-3 `FrameRef` columns (no
    `payload_sha256`)."""
    return {
        "frame_id": frame_id,
        "image_id": image_id,
        "channel": 0,
        "stream": "main",
        "codec": "h264",
        "frame_type": "I",
        "header_offset": 0,
        "payload_offset": 8,
        "payload_len": 16,
        "ts_header_us": 0,
        "ts_index_us": 0,
        "width": 64,
        "height": 64,
        "source": "index",
        "recording_id": recording_id,
        "deleted": False,
        "ts_osd_us": None,
        "ts_norm_us": None,
        "norm_confidence": None,
        "motion_score": None,
    }


def _write_old_schema_frames_parquet(index_dir: Path, image_id: str, rows: list[dict]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    from pramaan_core.frames import SCHEMA as FRAME_SCHEMA

    old_schema = pa.schema([f for f in FRAME_SCHEMA if f.name != "payload_sha256"])
    columns: dict[str, list] = {name: [row[name] for row in rows] for name in old_schema.names}
    table = pa.table(columns, schema=old_schema)
    pq.write_table(table, index_dir / f"frames-{image_id}.parquet")


def test_list_frames_tolerates_parquet_missing_payload_sha256_column(tmp_path: Path) -> None:
    from pramaan_api.real import appdb, pipeline_store
    from pramaan_api.real.paths import case_dir

    data_dir = str(tmp_path / "data")
    cid = "case_old_schema"
    appdb.case_db(data_dir, cid)  # creates case.db so get_frame_with_case can find this case
    index_dir = case_dir(data_dir, cid) / "index"
    index_dir.mkdir(parents=True)

    row = _old_schema_frame_row(
        frame_id="frm_deadbeefdeadbeefdeadbeef", image_id="img_old", recording_id="rec_old"
    )
    _write_old_schema_frames_parquet(index_dir, "img_old", [row])

    frames = pipeline_store.list_frames(data_dir, cid)
    assert len(frames) == 1
    assert frames[0].frame_id == "frm_deadbeefdeadbeefdeadbeef"
    assert frames[0].payload_sha256 is None

    assert pipeline_store.count_frames(data_dir, cid) == 1

    found = pipeline_store.get_frame_with_case(data_dir, "frm_deadbeefdeadbeefdeadbeef")
    assert found is not None
    assert found[0] == cid
    assert found[1].payload_sha256 is None


def test_list_frames_tolerates_mixed_old_and_new_schema_files(tmp_path: Path) -> None:
    """One image scanned before FIX-3 (no `payload_sha256` column) and one
    scanned after, both indexed under the same case — `union_by_name`
    lets the glob mix per-file schemas."""
    from pramaan_api.real import pipeline_store
    from pramaan_api.real.paths import case_dir
    from pramaan_core.frames import write_frames
    from pramaan_core.models import FrameRef

    data_dir = str(tmp_path / "data")
    cid = "case_mixed_schema"
    index_dir = case_dir(data_dir, cid) / "index"
    index_dir.mkdir(parents=True)

    old_row = _old_schema_frame_row(
        frame_id="frm_aaaaaaaaaaaaaaaaaaaaaaaa", image_id="img_old", recording_id="rec_old"
    )
    _write_old_schema_frames_parquet(index_dir, "img_old", [old_row])

    new_frame = FrameRef(
        frame_id="frm_bbbbbbbbbbbbbbbbbbbbbbbb",
        image_id="img_new",
        channel=0,
        stream="main",
        codec="h264",
        frame_type="I",
        header_offset=0,
        payload_offset=8,
        payload_len=16,
        ts_header_us=1,
        ts_index_us=1,
        width=64,
        height=64,
        source="index",
        recording_id="rec_new",
        deleted=False,
        payload_sha256="c" * 64,
    )
    write_frames(case_dir(data_dir, cid), "img_new", [new_frame])

    frames = pipeline_store.list_frames(data_dir, cid)
    by_id = {f.frame_id: f for f in frames}
    assert len(frames) == 2
    assert by_id["frm_aaaaaaaaaaaaaaaaaaaaaaaa"].payload_sha256 is None
    assert by_id["frm_bbbbbbbbbbbbbbbbbbbbbbbb"].payload_sha256 == "c" * 64
    assert pipeline_store.count_frames(data_dir, cid) == 2


# --- FIX-4 (orchestrator add): offset pagination reaches frames with no
# ts_header_us (generic-carved footage, e.g. XSIM's blind carve pass) -----
#
# `from`/`to` filter on `ts_header_us` and correctly exclude NULL rows
# (`_frame_filter_clauses`), so a client that only had those two params
# could never page past frames with no device-clock header. `offset` pages
# over the same deterministic total order regardless.


def test_list_frames_offset_pagination_reaches_frames_with_no_timestamp(tmp_path: Path) -> None:
    from pramaan_api.real import pipeline_store
    from pramaan_api.real.paths import case_dir
    from pramaan_core.frames import write_frames
    from pramaan_core.models import FrameRef

    data_dir = str(tmp_path / "data")
    cid = "case_carved_no_ts"
    cdir = case_dir(data_dir, cid)

    # A handful of frames with a real ts_header_us and a handful of
    # generic-carved ones with none at all -- both must be reachable by
    # paging through with `offset`, and no frame must ever appear twice or
    # be skipped across a full page walk.
    frames = []
    for i in range(3):
        frames.append(
            FrameRef(
                frame_id=f"frm_ts{i:022d}",
                image_id="img_carved",
                channel=0,
                stream="main",
                codec="h264",
                frame_type="I",
                header_offset=None,
                payload_offset=i * 100,
                payload_len=50,
                ts_header_us=i * 1000,
                ts_index_us=None,
                width=None,
                height=None,
                source="index",
                recording_id=None,
                deleted=False,
                payload_sha256=None,
            )
        )
    for i in range(4):
        frames.append(
            FrameRef(
                frame_id=f"frm_nots{i:020d}",
                image_id="img_carved",
                channel=0,
                stream="main",
                codec="h264",
                frame_type="other",
                header_offset=None,
                payload_offset=10_000 + i * 100,
                payload_len=50,
                ts_header_us=None,  # generic-carved: no device-clock header
                ts_index_us=None,
                width=None,
                height=None,
                source="carved",
                recording_id=None,
                deleted=False,
                payload_sha256=None,
            )
        )
    write_frames(cdir, "img_carved", frames)

    total = pipeline_store.count_frames(data_dir, cid)
    assert total == len(frames) == 7

    # Page through with a small page size, walking every frame via offset,
    # exactly the way the frames router's `offset` query param is used.
    page_size = 3
    seen_ids: list[str] = []
    offset = 0
    for _ in range(10):  # generous upper bound on iterations
        page = pipeline_store.list_frames(data_dir, cid, limit=page_size, offset=offset)
        if not page:
            break
        seen_ids.extend(f.frame_id for f in page)
        offset += page_size

    assert len(seen_ids) == len(set(seen_ids)) == total, "no duplicates, none skipped"
    assert {f.frame_id for f in frames} == set(seen_ids)
    # The NULL-ts_header_us frames were genuinely reached, not silently
    # dropped by pagination.
    assert any(fid.startswith("frm_nots") for fid in seen_ids)

    # `from`/`to` remain unchanged and still correctly exclude NULL rows —
    # `offset` is additive, not a replacement.
    ts_only = pipeline_store.list_frames(data_dir, cid, frm=0, to=10_000)
    assert {f.frame_id for f in ts_only} == {f"frm_ts{i:022d}" for i in range(3)}


def test_frames_route_offset_query_param_pages_through_every_frame(
    real_client: TestClient, real_settings
) -> None:
    """Same scenario as ``test_list_frames_offset_pagination_reaches_frames
    _with_no_timestamp`` above, exercised through the actual HTTP route
    (``GET /cases/{cid}/frames?offset=...``) and its ``X-Total-Count``
    header, task FIX-4."""
    from pramaan_api.real.paths import case_dir
    from pramaan_core.frames import write_frames
    from pramaan_core.models import FrameRef

    case = real_client.post(
        "/api/cases", json={"case_number": "CR-FIX4-FRAME-OFFSET", "title": "offset paging"}
    ).json()
    cdir = case_dir(real_settings.data_dir, case["id"])

    frames = [
        FrameRef(
            frame_id=f"frm_x{i:022d}",
            image_id="img_x",
            channel=0,
            stream="main",
            codec="h264",
            frame_type="other" if i % 2 else "I",
            header_offset=None,
            payload_offset=i * 100,
            payload_len=50,
            # Every other frame is a generic-carved one with no
            # device-clock header at all.
            ts_header_us=None if i % 2 else i * 1000,
            ts_index_us=None,
            width=None,
            height=None,
            source="carved" if i % 2 else "index",
            recording_id=None,
            deleted=False,
            payload_sha256=None,
        )
        for i in range(6)
    ]
    write_frames(cdir, "img_x", frames)

    total_resp = real_client.get(f"/api/cases/{case['id']}/frames", params={"limit": 1})
    assert total_resp.status_code == 200, total_resp.text
    assert total_resp.headers["X-Total-Count"] == "6"

    seen_ids: list[str] = []
    for offset in range(0, 6, 2):
        page = real_client.get(
            f"/api/cases/{case['id']}/frames", params={"limit": 2, "offset": offset}
        )
        assert page.status_code == 200, page.text
        assert page.headers["X-Total-Count"] == "6"
        seen_ids.extend(f["frame_id"] for f in page.json())

    assert len(seen_ids) == len(set(seen_ids)) == 6
    assert {f.frame_id for f in frames} == set(seen_ids)
    assert any(f["ts_header_us"] is None for f in [f.model_dump() for f in frames])
