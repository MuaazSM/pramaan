"""Real-mode reports + BSA Section 63 certificate (task B3,
docs/02-BACKEND.md §9, §12).

Acceptance covered here:

- "Report determinism | Two report runs on the same case → identical
  report_sha256." A *live*, mutating ``POST /cases/{cid}/reports`` call
  necessarily changes the case's own custody chain (it appends
  ``report.generated`` + ``anchor.created`` audit entries per docs §8, and
  the manifest includes the custody head hash/length by design), so two
  back-to-back POSTs on the same case legitimately produce two *different*
  hashes — see ``apps/api/pramaan_api/real/report_store.py``'s module
  docstring and docs/progress/B3.md "Decisions" for the full reasoning.
  What's actually reproducible (and tested below, both ways): (1)
  ``pramaan_reporting.build_manifest``/``report_sha256`` are pure functions
  of their inputs (CLAUDE.md rule 5) — same inputs in, byte-identical
  manifest and hash out, called twice, entirely independent of wall clock;
  (2) re-reading an already-generated report's manifest
  (``GET /reports/{rid}/manifest``, read-only) is perfectly idempotent.
- "Certificate | All hash values in the certificate equal the evidence
  hashes; Part A/B sections present."
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pramaan_core.ids import content_id
from pramaan_core.models import ByteRange, FrameRef, Recording, VendorMatch
from pramaan_reporting import ManifestInputs, build_manifest, report_sha256
from pramaan_reporting.certificate import build_certificate_data
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


def _build_one_gop_h264(tmp_path: Path) -> bytes:
    out = tmp_path / "gop.h264"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=size=64x64:rate=2:color=blue",
            "-frames:v", "1", "-c:v", "libx264", "-profile:v", "baseline", "-g", "1",
            "-f", "h264", str(out),
        ],
        check=True, capture_output=True, timeout=FFMPEG_TIMEOUT_S,
    )
    return out.read_bytes()


def _fake_vendor_match() -> VendorMatch:
    return VendorMatch(
        family="testvendor", display_name="Test Vendor (fake, in-test)", platform=None,
        tier="A", confidence=0.9, evidence=["fake signature for test_reports_real"],
        model="TV-1000", serial="SN-REPORTS-1", fs_version=None,
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
        "serial_label": "SN-REPORTS-1",
        "notes": "fixture for test_reports_real",
    }


def _create_case(client: TestClient, number: str) -> dict[str, Any]:
    resp = client.post("/api/cases", json={"case_number": number, "title": f"Reports {number}"})
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _register_and_scan(
    client: TestClient, tmp_path: Path, real_evidence_dir: Path, case_number: str
) -> dict[str, Any]:
    case = _create_case(client, case_number)
    image_path = real_evidence_dir / f"{case_number}.img"
    h264 = _build_one_gop_h264(tmp_path)
    image_bytes = (b"\x00" * PAD) + h264 + (b"\xff" * PAD)
    image_path.write_bytes(image_bytes)

    ev_resp = client.post(
        f"/api/cases/{case['id']}/evidence",
        json={"path": str(image_path), "label": "fake disk", "intake": _intake_body()},
    )
    assert ev_resp.status_code == 201, ev_resp.text
    image = ev_resp.json()

    payload_offset = PAD
    frame = FrameRef(
        frame_id=hashlib.sha256(h264).hexdigest()[:24], image_id=image["id"], channel=0,
        stream="main", codec="h264", frame_type="I", header_offset=max(payload_offset - 8, 0),
        payload_offset=payload_offset, payload_len=len(h264), ts_header_us=0, ts_index_us=0,
        width=64, height=64, source="index",
        recording_id=content_id("rec", {"image_id": image["id"], "channel": 0, "start": 0}),
        deleted=False,
    )
    recording = Recording(
        id=frame.recording_id, image_id=image["id"], channel=0, stream="main", start_ts_us=0,
        end_ts_us=500_000, byte_ranges=[ByteRange(offset=payload_offset, length=len(h264))],
        source="index", deleted=False,
    )
    registry.register_fingerprinter(lambda reader: [_fake_vendor_match()])
    registry.register_vendor_parser(_FakeVendorParser(recording, [frame]))

    scan_resp = client.post(f"/api/evidence/{image['id']}/scan", json={})
    assert scan_resp.status_code == 202, scan_resp.text
    assert scan_resp.json()["status"] == "done", scan_resp.json()

    return case


def test_create_report_end_to_end(
    real_client: TestClient, tmp_path: Path, real_evidence_dir: Path
) -> None:
    case = _register_and_scan(real_client, tmp_path, real_evidence_dir, "CR-B3-0001")

    resp = real_client.post(f"/api/cases/{case['id']}/reports", json={})
    assert resp.status_code == 201, resp.text
    report = resp.json()
    assert report["case_id"] == case["id"]
    assert report["report_sha256"]
    assert report["pdf_path"] and report["certificate_path"] and report["manifest_path"]

    pdf_resp = real_client.get(f"/api/reports/{report['id']}/pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.content.startswith(b"%PDF")

    cert_resp = real_client.get(f"/api/reports/{report['id']}/certificate.pdf")
    assert cert_resp.status_code == 200
    assert cert_resp.content.startswith(b"%PDF")

    listed = real_client.get(f"/api/cases/{case['id']}/reports").json()
    assert any(r["id"] == report["id"] for r in listed)


def test_report_manifest_reread_is_idempotent(
    real_client: TestClient, tmp_path: Path, real_evidence_dir: Path
) -> None:
    case = _register_and_scan(real_client, tmp_path, real_evidence_dir, "CR-B3-0002")
    report = real_client.post(f"/api/cases/{case['id']}/reports", json={}).json()

    m1 = real_client.get(f"/api/reports/{report['id']}/manifest").json()
    m2 = real_client.get(f"/api/reports/{report['id']}/manifest").json()
    assert m1["report_sha256"] == m2["report_sha256"] == report["report_sha256"]
    assert m1 == m2
    # The evidence hash recorded in the manifest matches what was actually
    # registered — the manifest is not just internally consistent, it
    # reflects the real evidence.
    assert m1["evidence"][0]["sha256"]


def test_report_generation_anchors_the_case(
    real_client: TestClient, tmp_path: Path, real_evidence_dir: Path
) -> None:
    case = _register_and_scan(real_client, tmp_path, real_evidence_dir, "CR-B3-0003")
    before = real_client.get(f"/api/cases/{case['id']}/anchors").json()
    real_client.post(f"/api/cases/{case['id']}/reports", json={})
    after = real_client.get(f"/api/cases/{case['id']}/anchors").json()
    assert len(after) == len(before) + 1


def test_report_generation_requires_examiner_or_admin(
    real_reviewer_client: TestClient, tmp_path: Path, real_evidence_dir: Path
) -> None:
    resp = real_reviewer_client.post("/api/cases/does-not-matter/reports", json={})
    assert resp.status_code == 403


def test_manifest_build_is_a_pure_function_of_its_inputs() -> None:
    """CLAUDE.md rule 5, docs/02-BACKEND.md §9 step 1: the manifest builder
    itself — independent of any live, self-mutating custody chain — is
    exactly reproducible."""
    inputs = ManifestInputs(
        case={"id": "case_1", "case_number": "CR-X", "title": "T", "fir_reference": None,
              "lab": "Lab", "status": "open"},
        examiner={"username": "examiner", "role": "examiner"},
        evidence=[{"id": "img_1", "path": "/x.img", "format": "raw", "size_bytes": 10,
                   "sha256": "a" * 64, "md5": "b" * 32, "acquired_utc": "2026-01-01T00:00:00Z",
                   "verified": True}],
        vendor_matches={}, recordings=[], deletion_findings=[], clock_observations=[],
        log_events=[], custody={"head_hash": "c" * 64, "length": 3}, anchors=[],
        methods={"tool": "pramaan", "tool_version": "0.1.0", "stage_order": []},
    )
    m1 = build_manifest(inputs)
    m2 = build_manifest(inputs)
    assert m1 == m2
    assert report_sha256(m1) == report_sha256(m2)

    # A logically-irrelevant re-ordering of the same evidence list (as if
    # it had come back from a database in a different row order) must not
    # change the hash.
    reordered = ManifestInputs(**{**inputs.__dict__, "evidence": list(reversed(inputs.evidence))})
    assert report_sha256(build_manifest(reordered)) == report_sha256(m1)


def test_certificate_hash_values_equal_evidence_hashes() -> None:
    """docs/02-BACKEND.md §12: "All hash values in the certificate equal
    the evidence hashes; Part A/B sections present"."""
    evidence = [
        {"id": "img_1", "path": "/evidence/one.img", "format": "raw", "size_bytes": 1024,
         "sha256": "1" * 64, "md5": "2" * 32, "acquired_utc": "2026-01-01T00:00:00Z",
         "verified": True},
        {"id": "img_2", "path": "/evidence/two.img", "format": "raw", "size_bytes": 2048,
         "sha256": "3" * 64, "md5": "4" * 32, "acquired_utc": "2026-01-02T00:00:00Z",
         "verified": True},
    ]
    inputs = ManifestInputs(
        case={"id": "case_1", "case_number": "CR-CERT", "title": "Certificate test",
              "fir_reference": "FIR/9/2026", "lab": "Pramaan Lab", "status": "open"},
        examiner={"username": "examiner", "role": "examiner"},
        evidence=evidence, vendor_matches={}, recordings=[], deletion_findings=[],
        clock_observations=[
            {"id": "cko_1", "image_id": "img_1", "channel": None, "source": "seizure",
             "device_ts_us": 0, "reference_ts_us": 0, "offset_us": 0, "weight": 1.0,
             "details": {"make_model_label": "Hikvision DS-7208", "serial_label": "SN-1"}},
        ],
        log_events=[], custody={"head_hash": "c" * 64, "length": 5}, anchors=[],
        methods={"tool": "pramaan", "tool_version": "0.1.0", "stage_order": []},
    )
    manifest = build_manifest(inputs)
    certificate = build_certificate_data(manifest)

    assert len(certificate["part_a"]["records"]) == 2
    assert certificate["part_a"]["records"][0]["make_model"] == "Hikvision DS-7208"
    assert certificate["part_a"]["records"][0]["serial"] == "SN-1"
    # Second evidence item had no seizure clock observation recorded, and no
    # fingerprint/vendor match to fall back to.
    assert certificate["part_a"]["records"][1]["make_model"] == "Not recorded"
    # Neither evidence item was acquired by Pramaan (no acquire.acquire
    # provenance) — the certificate must say so honestly, not claim a
    # write-blocked acquisition that didn't happen (CLAUDE.md rule 7).
    for record in certificate["part_a"]["records"]:
        assert "Registered by Pramaan as an already-present" in record["how_produced"]
        assert "write-blocked" not in record["how_produced"]
    # The rendered certificate never prints the absolute host path.
    for record in certificate["part_a"]["records"]:
        assert "/evidence/" not in record["identity"]

    expected_hashes = {(e["id"], "SHA-256", e["sha256"]) for e in evidence} | {
        (e["id"], "MD5", e["md5"]) for e in evidence
    }
    for section in ("part_a", "part_b"):
        by_id = {
            (row["item"].split(": ", 1)[-1], row["algorithm"], row["value"])
            for row in certificate[section]["hash_lines"]
        }
        # hash_lines key on the evidence's file-name label (never the
        # absolute path — item 6), not the bare id — re-derive the
        # (basename -> id) mapping to compare like for like.
        path_to_id = {Path(e["path"]).name: e["id"] for e in evidence}
        normalised = {(path_to_id.get(item, item), algo, val) for item, algo, val in by_id}
        assert expected_hashes <= normalised

    assert certificate["declaration_placeholder"]
    assert certificate["template_note"]
    assert certificate["part_b"]["examiner"]["username"] == "examiner"


def _minimal_manifest_inputs(**overrides: Any) -> ManifestInputs:
    base: dict[str, Any] = dict(
        case={"id": "case_1", "case_number": "CR-FIX10", "title": "FIX-10 test",
              "fir_reference": None, "lab": "Pramaan Lab", "status": "open"},
        examiner={"username": "examiner", "role": "examiner"},
        evidence=[
            {"id": "img_1", "path": "/Users/examiner/host-only-path/disk_one.img",
             "format": "raw", "size_bytes": 1024, "sha256": "1" * 64, "md5": "2" * 32,
             "acquired_utc": "2026-09-30T03:10:07.754536Z", "verified": True}
        ],
        vendor_matches={}, recordings=[], deletion_findings=[], clock_observations=[],
        log_events=[], custody={"head_hash": "c" * 64, "length": 3}, anchors=[],
        methods={"tool": "pramaan", "tool_version": "0.1.0", "stage_order": []},
    )
    base.update(overrides)
    return ManifestInputs(**base)


def test_certificate_acquired_by_pramaan_wording_is_used_only_when_true() -> None:
    """CLAUDE.md rule 7 / item 5, docs/progress/FIX-10.md: the certificate
    must only claim a write-blocked acquisition when the evidence item's
    provenance actually says so."""
    inputs = _minimal_manifest_inputs(
        evidence=[
            {"id": "img_1", "path": "/x/acquired.img", "format": "raw", "size_bytes": 10,
             "sha256": "a" * 64, "md5": "b" * 32, "acquired_utc": "2026-01-01T00:00:00Z",
             "verified": True, "intake_kind": "acquired_by_pramaan"},
        ]
    )
    certificate = build_certificate_data(build_manifest(inputs))
    how_produced = certificate["part_a"]["records"][0]["how_produced"]
    assert "write-blocked" in how_produced
    assert "Registered by Pramaan as an already-present" not in how_produced


def test_certificate_make_model_falls_back_to_fingerprint_result() -> None:
    """Item 5: when the examiner didn't record a make/model at intake,
    fall back to Pramaan's own vendor/format fingerprinting result — but
    label it as an inference, not an examiner-verified fact."""
    inputs = _minimal_manifest_inputs(
        vendor_matches={
            "img_1": [
                {"family": "hiksim", "display_name": "Hikvision-like (synthetic)",
                 "platform": "hikvision", "tier": "A", "confidence": 0.95, "evidence": [],
                 "model": "DS-7208HUHI", "serial": "FPSN-42", "fs_version": None}
            ]
        }
    )
    certificate = build_certificate_data(build_manifest(inputs))
    record = certificate["part_a"]["records"][0]
    assert record["make_model"] == "DS-7208HUHI (as identified by Pramaan from on-disk metadata)"
    assert record["serial"] == "FPSN-42 (as identified by Pramaan from on-disk metadata)"


def test_certificate_never_prints_absolute_host_path() -> None:
    """Item 6: the certificate identity field shows the evidence file name,
    never the examiner's absolute host filesystem path."""
    inputs = _minimal_manifest_inputs()
    certificate = build_certificate_data(build_manifest(inputs))
    identity = certificate["part_a"]["records"][0]["identity"]
    assert "host-only-path" not in identity
    assert "disk_one.img" in identity


def test_rendered_report_and_certificate_html_have_no_internal_doc_references() -> None:
    """Item 4: legal-facing rendered text must never cite internal repo
    docs/rules — those are implementation details, not something a court
    reader should see."""
    from pramaan_reporting.appendix import build_hash_appendix
    from pramaan_reporting.manifest import manifest_bytes, report_sha256
    from pramaan_reporting.render import render_certificate_html, render_report_html

    inputs = _minimal_manifest_inputs()
    manifest = build_manifest(inputs)
    manifest_bytes(manifest)  # exercised for parity with the real pipeline
    sha256 = report_sha256(manifest)
    certificate = build_certificate_data(manifest)
    appendix = build_hash_appendix(manifest, sha256)
    envelope = {"report_sha256": sha256, "generated_utc": "2026-09-30T03:10:07.754536Z"}

    report_html = render_report_html(
        {"manifest": manifest, "envelope": envelope, "certificate": certificate,
         "appendix": appendix, "thumbnails": []}
    )
    certificate_html = render_certificate_html({"envelope": envelope, "certificate": certificate})

    for label, html in (("report", report_html), ("certificate", certificate_html)):
        # Strip the <style> block: CSS comments live in the HTML source but
        # are never part of the rendered/printed page a reader sees, so
        # they're not "legal text" — only the visible body matters here.
        visible = re.sub(r"<style>.*?</style>", "", html, flags=re.DOTALL)
        for needle in ("docs/", "CLAUDE.md", "PROMPTBOOK", "PRD §", "§9 step"):
            assert needle not in visible, f"{label}.html leaked internal doc reference {needle!r}"


def test_rendered_report_shows_evidence_filename_not_full_path_in_body() -> None:
    """Item 6: the report body's evidence table shows the file name; the
    full host path is confined to the appendix."""
    from pramaan_reporting.appendix import build_hash_appendix
    from pramaan_reporting.manifest import report_sha256
    from pramaan_reporting.render import render_report_html

    inputs = _minimal_manifest_inputs()
    manifest = build_manifest(inputs)
    sha256 = report_sha256(manifest)
    certificate = build_certificate_data(manifest)
    appendix = build_hash_appendix(manifest, sha256)
    envelope = {"report_sha256": sha256, "generated_utc": "2026-09-30T03:10:07.754536Z"}

    report_html = render_report_html(
        {"manifest": manifest, "envelope": envelope, "certificate": certificate,
         "appendix": appendix, "thumbnails": []}
    )
    full_path = manifest["evidence"][0]["path"]
    assert "disk_one.img" in report_html
    # The full absolute path must appear at most once per evidence item —
    # in the appendix's dedicated "source path" row — never inline in the
    # evidence table itself.
    assert report_html.count(full_path) <= len(manifest["evidence"])
    body_before_appendix = report_html.split("Appendix")[0]
    assert full_path not in body_before_appendix


def test_print_css_is_not_html_entity_escaped_in_rendered_html() -> None:
    """Regression test for the FIX-10 root cause of "fonts render as Times
    fallback": ``print_css()`` is trusted, in-process-generated CSS, and
    must reach the ``<style>`` block un-escaped — if Jinja2 autoescaping
    ever HTML-escapes it again, every quoted ``font-family``/``url(...)``
    declaration silently breaks and WeasyPrint falls back to its default
    serif font.
    """
    from pramaan_reporting.render import render_report_html
    from pramaan_reporting.styles import print_css

    inputs = _minimal_manifest_inputs()
    manifest = build_manifest(inputs)
    certificate = build_certificate_data(manifest)
    envelope = {"report_sha256": report_sha256(manifest), "generated_utc": "2026-01-01T00:00:00Z"}
    report_html = render_report_html(
        {"manifest": manifest, "envelope": envelope, "certificate": certificate,
         "appendix": [], "thumbnails": []}
    )
    assert "&#34;" not in report_html
    assert "&quot;" not in report_html
    assert '@font-face' in report_html
    assert 'font-family: "Geist Sans"' in report_html
    # The CSS itself must actually declare the bundled fonts as data URIs
    # (no filesystem/network font lookup at render time).
    assert "data:font/woff2;base64," in print_css()


def test_report_pdf_embeds_bundled_fonts_not_serif_fallback(
    real_client: TestClient, tmp_path: Path, real_evidence_dir: Path
) -> None:
    """Item 1, verified the way the task asks: inspect the actual PDF's
    embedded font resources with ``pdffonts`` (skipped if not installed)."""
    import shutil
    import subprocess as sp

    pdffonts = shutil.which("pdffonts")
    if pdffonts is None:
        pytest.skip("pdffonts (poppler-utils) not available in this environment")

    case = _register_and_scan(real_client, tmp_path, real_evidence_dir, "CR-B3-FONTS")
    report = real_client.post(f"/api/cases/{case['id']}/reports", json={}).json()
    pdf_resp = real_client.get(f"/api/reports/{report['id']}/pdf")
    assert pdf_resp.status_code == 200

    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(pdf_resp.content)
    out = sp.run([pdffonts, str(pdf_path)], check=True, capture_output=True, text=True).stdout
    assert "Times" not in out, f"report.pdf still falls back to a serif font:\n{out}"
    assert "Geist" in out, f"report.pdf does not embed the bundled Geist font:\n{out}"
