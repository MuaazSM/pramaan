#!/usr/bin/env python3
"""``just demo`` — seed the demo case through the real API (docs/05-INFRA-QA.md §3).

What this does, in order:

1. Ensures the synthetic corpus exists (runs ``just corpus`` if
   ``corpus/images/hiksim_format.img`` is missing).
2. Starts ``apps/api`` as a real subprocess in **real mode**
   (``PRAMAAN_STUB_MODE=0``), backed by a gitignored data dir under
   ``data/`` and ``EVIDENCE_ROOTS`` pointed at ``corpus/images``.
3. Talks to it over plain HTTP (never imports API internals — this is a
   black-box smoke test of the real contract): logs in as
   ``examiner``/``demo``, creates case ``CR-2026-0412`` (reusing it if it
   already exists), registers each demo evidence image (``hiksim_format``,
   ``dhsim_format``, ``hwsim_format``, ``xsim_unknown`` — see
   ``DEMO_EVIDENCE``) via ``POST /cases/{cid}/evidence`` (never opens/
   copies the image itself — CLAUDE.md rule 1/2: only the API's own
   ``pramaan_core.acquire`` path touches evidence bytes), runs the full
   scan pipeline job on each, and waits for completion by polling
   ``GET /jobs/{jid}``.
4. Confirms ``xsim_unknown``'s inferred layout through the real API
   (``POST /inferred-layouts/{lid}/confirm``, task FIX-1) — best-effort,
   see ``try_confirm_inferred_layout``.
5. Generates a signed report (PDF + BSA certificate) and one signed
   export for the demo case (task B3's ``/cases/{cid}/reports`` and
   ``/cases/{cid}/exports`` routes), then verifies the export via
   ``POST /exports/verify``.
6. Prints a summary (recordings, recovered/deleted frames, stage
   statuses, report/export paths+hashes) per evidence image.
7. Stops the API subprocess, unless ``--keep-running`` was passed.

Idempotent and safe to re-run: case lookup is by ``case_number``, evidence
ids are content-derived (registering the same image twice is a no-op),
scan stages are resumable (a second scan on the same evidence skips every
stage via its input-hash marker — see ``docs/progress/B1.md``/``B2.md``),
exports are genuinely idempotent (task B3), and an existing report is
reused rather than regenerated (see ``get_or_create_report``'s docstring
for why report generation itself isn't content-idempotent by design).

Usage::

    uv run python tools/demo/demo.py [--keep-running] [--timeout SECONDS] [--port PORT]

Exits 0 on success (``STRICT_IMAGES`` all scanned with status "done" and
recordings > 0; a report and a verified signed export produced);
non-zero otherwise, with a message on stderr. ``BEST_EFFORT_IMAGES`` are
always attempted and always reported, but never gate the exit code — see
that constant's docstring.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_IMAGES = REPO_ROOT / "corpus" / "images"
DATA_DIR = REPO_ROOT / "data" / "demo"

CASE_NUMBER = "CR-2026-0412"
CASE_TITLE = "Shopfront burglary, Andheri"
CASE_LAB = "Pramaan Digital Forensics Lab"

USERNAME = "examiner"
PASSWORD = "demo"

# Evidence images registered by `just demo`, in order. Append a new
# (image_stem, label) pair here to bring another corpus image into the
# demo — nothing else in this script needs to change.
DEMO_EVIDENCE: list[tuple[str, str]] = [
    ("hiksim_format", "DVR HDD, shop front, seized 12 Mar (Hikvision-format, deleted footage)"),
    ("dhsim_format", "DVR HDD, second unit (Dahua-format, deleted footage)"),
    ("hwsim_format", "NVR disk, third unit (Honeywell-format GPT disk, deleted footage)"),
    ("xsim_unknown", "Unlabelled DVR disk, fourth unit (unknown/Tier B format, needs inference)"),
]

# The image the original Wave 2 gate cared about — its scan must succeed
# with recordings > 0 for `just demo` to exit 0 (kept for the exact wording
# the acceptance check and tests/e2e/test_demo_flow.py already assert on).
REQUIRED_IMAGE = "hiksim_format"

# Images whose scan is required to fully succeed (job "done", recordings
# > 0) for `just demo` to exit 0 — proven working end to end in real mode.
# `hwsim_format` joined this set once its scan started reliably reaching
# job "done" with recordings > 0 (the real HwsimParser's own index parse).
# One remaining, non-blocking wrinkle (see docs/progress/FIX-2.md
# "Cross-workstream issues"): its "clips" stage still can't remux a
# playable clip for it. This is *not* a missing-bytes problem — the
# on-disk image genuinely carries SPS/PPS NALs in-band, each behind its
# own 20-byte header, immediately before every IDR access unit, exactly
# per docs/01-FORENSIC-CORE.md §4.6 (confirmed by walking the raw bytes
# directly). The gap is in `packages/formats/pramaan_formats/hwsim.py`'s
# `HwsimParser.iter_frames`, which returns only the trailing slice NAL as
# a live frame's payload, discarding the SPS/PPS/SEI NALs that precede it
# on disk — not owned by this task. The stage now reports that
# per-recording rather than crashing the whole scan request, which is why
# hwsim_format's scan itself can be required here even though its clips
# still aren't playable.
STRICT_IMAGES = {"hiksim_format", "dhsim_format", "hwsim_format"}

# Best-effort images: always registered and scanned, and their result is
# always reported honestly in the summary, but a failure here does not by
# itself fail `just demo`'s exit code. `xsim_unknown` is Tier B (no
# VendorParser — docs/01-FORENSIC-CORE.md §4.8): its scan reaches job
# status "done" but `recordings` stays 0 until its inferred layout is
# confirmed (`try_confirm_inferred_layout` below), and confirmation itself
# is best-effort (task FIX-1's real-mode confirm route).
BEST_EFFORT_IMAGES = {"xsim_unknown"}

# Fixed, deterministic SWGDE intake (CLAUDE.md rule 5: determinism — no
# wall-clock values). Mirrors corpus/truth/hiksim_format.json's seizure
# block (docs/05-INFRA-QA.md §4.4).
INTAKE: dict[str, str] = {
    "seized_at_local": "2026-03-12T16:40:00+05:30",
    "dvr_displayed_time": "2026-03-12T16:41:40",
    "reference_time": "2026-03-12T16:36:28+05:30",
    "reference_source": "NTP phone clock",
    "timezone": "Asia/Kolkata",
    "write_blocker": "Tableau T35u",
    "notes": "just demo: seeded via tools/demo/demo.py",
}

CSRF_COOKIE_NAME = "pramaan_csrf"
CSRF_HEADER_NAME = "x-csrf-token"


class DemoError(RuntimeError):
    """A demo-flow failure worth a clean, non-traceback error message."""


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def tail(path: Path, n: int = 60) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return f"(could not read {path})"
    return "\n".join(lines[-n:])


def ensure_corpus() -> None:
    target = CORPUS_IMAGES / f"{REQUIRED_IMAGE}.img"
    if target.exists():
        return
    print(f"demo: {target} missing — running `just corpus` ...", file=sys.stderr)
    result = subprocess.run(["just", "corpus"], cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        raise DemoError(f"`just corpus` exited {result.returncode}")
    if not target.exists():
        raise DemoError(f"`just corpus` completed but {target} is still missing")


def start_api(port: int) -> tuple[subprocess.Popen[bytes], Path]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DATA_DIR / "api.log"
    env = os.environ.copy()
    # NOTE: the field is `Settings.data_dir`; pydantic-settings' env_prefix
    # ("PRAMAAN_") + field name means the real env var is
    # `PRAMAAN_DATA_DIR`, not `PRAMAAN_DATA` (docs/02-BACKEND.md §3's
    # prose is shorthand) — verified directly against `Settings()`.
    env["PRAMAAN_DATA_DIR"] = str(DATA_DIR)
    env["PRAMAAN_STUB_MODE"] = "0"
    env["PRAMAAN_EVIDENCE_ROOTS"] = json.dumps([str(CORPUS_IMAGES)])
    env.setdefault("PRAMAAN_JOB_BACKEND", "inline")
    log_file = log_path.open("wb")
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "pramaan_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return proc, log_path


def wait_healthy(
    base_url: str, proc: subprocess.Popen[bytes], log_path: Path, deadline: float
) -> None:
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise DemoError(
                f"API process exited early (code {proc.returncode}). Last log lines:\n"
                f"{tail(log_path)}"
            )
        try:
            resp = httpx.get(f"{base_url}/api/system/health", timeout=2.0)
            if resp.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise DemoError(
        f"API did not become healthy within the timeout. Last log lines:\n{tail(log_path)}"
    )


def stop_api(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def csrf_headers(client: httpx.Client) -> dict[str, str]:
    token = client.cookies.get(CSRF_COOKIE_NAME)
    if not token:
        raise DemoError("no CSRF cookie set — did login() run first?")
    return {CSRF_HEADER_NAME: token}


def login(client: httpx.Client) -> None:
    resp = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    if resp.status_code != 200:
        raise DemoError(f"login failed: {resp.status_code} {resp.text}")


def get_or_create_case(client: httpx.Client) -> dict[str, Any]:
    resp = client.get("/api/cases")
    resp.raise_for_status()
    for case in resp.json():
        if case["case_number"] == CASE_NUMBER:
            return dict(case)
    resp = client.post(
        "/api/cases",
        json={
            "case_number": CASE_NUMBER,
            "title": CASE_TITLE,
            "fir_reference": None,
            "lab": CASE_LAB,
        },
        headers=csrf_headers(client),
    )
    if resp.status_code >= 400:
        raise DemoError(f"case creation failed: {resp.status_code} {resp.text}")
    return dict(resp.json())


def register_evidence(
    client: httpx.Client, case_id: str, image_path: Path, label: str
) -> dict[str, Any]:
    resp = client.post(
        f"/api/cases/{case_id}/evidence",
        json={"path": str(image_path), "label": label, "intake": INTAKE},
        headers=csrf_headers(client),
    )
    if resp.status_code >= 400:
        raise DemoError(f"registering {image_path} failed: {resp.status_code} {resp.text}")
    return dict(resp.json())


def run_scan(client: httpx.Client, evidence_id: str) -> dict[str, Any]:
    resp = client.post(
        f"/api/evidence/{evidence_id}/scan",
        json={},
        headers=csrf_headers(client),
    )
    if resp.status_code >= 400:
        raise DemoError(f"scan of {evidence_id} failed to queue: {resp.status_code} {resp.text}")
    return dict(resp.json())


def poll_job(client: httpx.Client, job_id: str, deadline: float) -> dict[str, Any]:
    while True:
        resp = client.get(f"/api/jobs/{job_id}")
        resp.raise_for_status()
        job = resp.json()
        if job["status"] in ("done", "failed"):
            return dict(job)
        if time.monotonic() > deadline:
            raise DemoError(f"job {job_id} did not finish before the timeout")
        time.sleep(0.5)


_TOTAL_COUNT_HEADERS = ("x-total-count", "x-total", "total-count")


def _response_total(resp: httpx.Response) -> int | None:
    """``None`` unless the response carries a parseable total-count header
    (FIX-1 is adding one to ``GET /cases/{cid}/frames`` — docs/02-BACKEND.md
    §4's pagination note). Checked case-insensitively under a few
    plausible header-name spellings since the exact name isn't frozen yet.
    """
    for name in _TOTAL_COUNT_HEADERS:
        value = resp.headers.get(name)
        if value is not None:
            try:
                return int(value)
            except ValueError:
                continue
    return None


def summarize(client: httpx.Client, case_id: str, evidence_id: str) -> dict[str, Any]:
    """Recordings + recovered-(carved)-frame counts for one evidence image.

    ``GET /cases/{cid}/recordings`` is case-wide but unpaginated, so the
    recordings count (filtered client-side to this ``image_id``) is always
    exact. ``GET /cases/{cid}/frames`` has no ``image_id`` filter and a
    hard 500-row page cap (docs/02-BACKEND.md §4) shared across every
    evidence image in the case, so a single case-wide request can silently
    truncate before this image's rows are all seen once a second evidence
    image has also been scanned. Querying per channel (using this image's
    own recording channels, so we never guess) keeps each request's raw
    row count far under the cap for this demo corpus; ``truncated`` is
    still reported honestly (based on the *raw*, pre-filter page length)
    in case a future corpus image blows past it anyway.

    An ``image_id`` query param is opportunistically also sent on every
    request (harmless no-op if the API doesn't recognise it yet — extra
    query params are ignored, never rejected).

    Exact totals: if the response exposes a total-count header (see
    ``_response_total``) *and* every row actually returned for a given
    per-channel request already belongs to this ``evidence_id`` (i.e. the
    query wasn't observably mixing in another image's frames for that
    channel), that header value is this image's true per-channel total —
    trustworthy regardless of whether the header itself is case-wide or
    already server-side filtered to this image, since in that situation
    the two are provably the same number. If even one per-channel request
    doesn't meet that bar, the whole summary honestly falls back to the
    raw-row / lower-bound wording rather than mixing an exact number for
    some channels with a guessed one for others.
    """
    recs = client.get(f"/api/cases/{case_id}/recordings")
    recs.raise_for_status()
    recordings = [r for r in recs.json() if r["image_id"] == evidence_id]
    channels = sorted({r["channel"] for r in recordings if r.get("channel") is not None})

    # Count rows per page, not distinct `frame_id`s: `frame_id` is a
    # content hash of the payload (pramaan_core.models.FrameRef), and this
    # low-motion synthetic corpus has many byte-identical carved frames at
    # different physical offsets — each is still a distinct recovered
    # frame and must be counted once, not deduplicated away.
    carved_count = 0
    truncated = False
    exact_total = 0
    exact_reliable = True
    requests = [{"channel": c} for c in channels] or [{}]
    for extra_params in requests:
        resp = client.get(
            f"/api/cases/{case_id}/frames",
            params={
                "source": "carved",
                "limit": 500,
                "image_id": evidence_id,
                **extra_params,
            },
        )
        resp.raise_for_status()
        page = resp.json()
        if len(page) >= 500:
            truncated = True
        page_own = sum(1 for f in page if f["image_id"] == evidence_id)
        carved_count += page_own
        total = _response_total(resp)
        if total is None or page_own != len(page):
            exact_reliable = False
        else:
            exact_total += total

    if exact_reliable and requests != [{}]:
        return {
            "recordings": len(recordings),
            "recovered_frames": exact_total,
            "recovered_frames_truncated": False,
            "recovered_frames_exact": True,
        }
    return {
        "recordings": len(recordings),
        "recovered_frames": carved_count,
        "recovered_frames_truncated": truncated,
        "recovered_frames_exact": False,
    }


def print_summary(results: dict[str, dict[str, Any]]) -> None:
    print()
    print("=== just demo: summary ===")
    for name, r in results.items():
        job = r["job"]
        summary = r["summary"]
        print(f"\n[{name}]  evidence_id={r['evidence_id']}  job_status={job['status']}")
        for stage in job["stages"]:
            msg = f" — {stage['message']}" if stage.get("message") else ""
            print(f"    {stage['name']:<18s} {stage['status']}{msg}")
        note = " (page-capped, lower bound)" if summary["recovered_frames_truncated"] else ""
        print(f"    recordings: {summary['recordings']}")
        print(f"    recovered (deleted) frames: {summary['recovered_frames']}{note}")
    print()


def try_confirm_inferred_layout(client: httpx.Client, evidence_id: str) -> dict[str, Any]:
    """Best-effort: fetch ``xsim_unknown``'s inferred layout and confirm it
    via ``POST /inferred-layouts/{lid}/confirm`` (task FIX-1 is making this
    route real right now — real-mode confirm triggers the on-demand
    ``parse_inferred_layout`` reindex stage, which is what actually
    populates ``recordings``/``frames`` for a Tier B image;
    ``apps/worker/pramaan_worker/stages.py`` docstring). Never raises and
    never fails the overall demo run: if the route is still fixture-only
    (the real-mode branch hasn't landed yet), the confirm call 404s/500s
    against a lid the fixture store has never heard of, and that failure
    is reported here, not treated as a demo-breaking error — see
    docs/progress/FIX-2.md "Cross-workstream issues".
    """
    resp = client.get(f"/api/evidence/{evidence_id}/inferred-layout")
    if resp.status_code == 404:
        return {"status": "no_inferred_layout", "detail": "GET inferred-layout: 404"}
    if resp.status_code >= 400:
        return {
            "status": "get_failed",
            "detail": f"GET inferred-layout: {resp.status_code} {resp.text[:500]}",
        }
    layout = resp.json()
    lid = layout.get("id")
    if not lid:
        return {"status": "no_layout_id", "detail": f"inferred-layout response had no id: {layout}"}
    confirm_resp = client.post(
        f"/api/inferred-layouts/{lid}/confirm",
        headers=csrf_headers(client),
    )
    if confirm_resp.status_code >= 400:
        return {
            "status": "confirm_failed",
            "detail": f"POST confirm: {confirm_resp.status_code} {confirm_resp.text[:500]}",
        }
    return {"status": "confirmed", "layout_id": lid}


def get_or_create_report(client: httpx.Client, case_id: str) -> dict[str, Any]:
    """Reuse an existing report for the case if one exists, else generate
    one via ``POST /cases/{cid}/reports`` (task B3). Report generation is
    *not* content-idempotent by design (docs/progress/B3.md "Decisions":
    every successful report generation audits itself and anchors the
    case, so two live calls on the same case necessarily see different
    custody state and produce different ``report_sha256`` values) — reuse
    keeps repeated ``just demo`` runs from growing the case's report/anchor
    list without bound, rather than trying to force an idempotency the
    design intentionally doesn't provide.
    """
    resp = client.get(f"/api/cases/{case_id}/reports")
    resp.raise_for_status()
    existing = resp.json()
    if existing:
        return dict(existing[-1])
    resp = client.post(
        f"/api/cases/{case_id}/reports",
        json={"include_thumbnails": True},
        headers=csrf_headers(client),
    )
    if resp.status_code >= 400:
        raise DemoError(f"report generation failed: {resp.status_code} {resp.text}")
    return dict(resp.json())


def pick_live_recording(
    client: httpx.Client, case_id: str, evidence_id: str
) -> dict[str, Any] | None:
    resp = client.get(f"/api/cases/{case_id}/recordings")
    resp.raise_for_status()
    for rec in resp.json():
        if rec["image_id"] == evidence_id and not rec["deleted"]:
            return dict(rec)
    return None


def get_or_create_export(
    client: httpx.Client, case_id: str, recording_id: str
) -> dict[str, Any]:
    """Signed export for one recording (task B3). Genuinely idempotent —
    re-exporting the same recording by the same examiner returns the same
    export id/manifest hash/MP4 bytes (docs/progress/B3.md) — so this can
    always just call ``POST /cases/{cid}/exports`` without a
    reuse-lookup guard.
    """
    resp = client.post(
        f"/api/cases/{case_id}/exports",
        json={"recording_id": recording_id},
        headers=csrf_headers(client),
    )
    if resp.status_code >= 400:
        raise DemoError(f"export creation failed: {resp.status_code} {resp.text}")
    return dict(resp.json())


def verify_export(client: httpx.Client, export_id: str) -> tuple[bytes, dict[str, Any]]:
    file_resp = client.get(f"/api/exports/{export_id}/file")
    if file_resp.status_code >= 400:
        raise DemoError(
            f"fetching export {export_id} file failed: {file_resp.status_code} {file_resp.text}"
        )
    content = file_resp.content
    verify_resp = client.post(
        "/api/exports/verify",
        files={"file": ("export.mp4", content, "video/mp4")},
    )
    if verify_resp.status_code >= 400:
        raise DemoError(
            f"POST /exports/verify failed: {verify_resp.status_code} {verify_resp.text}"
        )
    return content, dict(verify_resp.json())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-running",
        action="store_true",
        help="leave the API running instead of stopping it at the end",
    )
    parser.add_argument(
        "--timeout", type=float, default=600.0, help="overall timeout in seconds (default 600)"
    )
    parser.add_argument(
        "--port", type=int, default=0, help="API port (default: pick a free port)"
    )
    args = parser.parse_args()

    deadline = time.monotonic() + args.timeout
    port = args.port or free_port()
    base_url = f"http://127.0.0.1:{port}"

    try:
        ensure_corpus()
    except DemoError as exc:
        print(f"demo: {exc}", file=sys.stderr)
        return 1

    proc, log_path = start_api(port)
    try:
        try:
            wait_healthy(base_url, proc, log_path, deadline)

            with httpx.Client(base_url=base_url, timeout=30.0) as client:
                login(client)
                case = get_or_create_case(client)
                case_id = case["id"]
                print(f"demo: case {case['case_number']} ({case_id})")

                # One evidence image's register/scan failing must not abort
                # the whole run — every image is attempted, and a failure
                # is recorded (never silently dropped) so the summary
                # still reports it. Defense in depth: earlier in this
                # task's own testing, hwsim_format's scan request crashed
                # outright (an uncaught exception from its "clips" stage —
                # see docs/progress/FIX-2.md "Cross-workstream issues");
                # that's since been fixed upstream to fail per-recording
                # instead, but this guard is kept in case another image
                # hits something similar.
                results: dict[str, dict[str, Any]] = {}
                for name, label in DEMO_EVIDENCE:
                    image_path = CORPUS_IMAGES / f"{name}.img"
                    if not image_path.exists():
                        print(
                            f"demo: skipping {name} — {image_path} not found in corpus",
                            file=sys.stderr,
                        )
                        continue
                    evidence_id: str | None = None
                    try:
                        evidence = register_evidence(client, case_id, image_path, label)
                        evidence_id = evidence["id"]
                        print(f"demo: registered {name} -> evidence_id={evidence_id}")
                        job = run_scan(client, evidence_id)
                        print(f"demo: scanning {name} (job {job['id']}) ...")
                        job = poll_job(client, job["id"], deadline)
                        summary = summarize(client, case_id, evidence_id)
                        results[name] = {
                            "evidence_id": evidence_id,
                            "job": job,
                            "summary": summary,
                        }
                    except (DemoError, httpx.HTTPStatusError) as exc:
                        print(f"demo: {name} scan FAILED: {exc}", file=sys.stderr)
                        results[name] = {
                            "evidence_id": evidence_id,
                            "job": {"status": "error", "stages": []},
                            "summary": {
                                "recordings": 0,
                                "recovered_frames": 0,
                                "recovered_frames_truncated": False,
                                "recovered_frames_exact": False,
                            },
                            "error": str(exc),
                        }

                print_summary(results)

                # STRICT_IMAGES must each scan to completion with a
                # non-empty index for `just demo` to exit 0.
                for name in STRICT_IMAGES:
                    r = results.get(name)
                    if r is None:
                        print(f"demo: {name} was never scanned", file=sys.stderr)
                        return 1
                    if r["job"]["status"] != "done":
                        print(
                            f"demo: {name} scan did not finish successfully "
                            f"(status={r['job']['status']})",
                            file=sys.stderr,
                        )
                        return 1
                    if r["summary"]["recordings"] <= 0:
                        print(f"demo: {name} scanned but produced 0 recordings", file=sys.stderr)
                        return 1

                # BEST_EFFORT_IMAGES: always attempted, always reported —
                # a failure here is printed plainly but never fails the
                # overall demo run (see BEST_EFFORT_IMAGES's docstring).
                for name in BEST_EFFORT_IMAGES:
                    r = results.get(name)
                    if r is None:
                        print(f"demo: {name} not in this corpus — skipped", file=sys.stderr)
                    elif r["job"]["status"] != "done":
                        print(
                            f"demo: {name} scan did not finish successfully "
                            f"(status={r['job']['status']}) — known cross-workstream issue, "
                            "see docs/progress/FIX-2.md",
                            file=sys.stderr,
                        )
                    else:
                        print(f"demo: {name} scanned OK (job status done).")

                # xsim_unknown: confirm its inferred layout through the
                # real API (FIX-1). Best-effort — never fails the demo run
                # (see try_confirm_inferred_layout's docstring).
                xsim_result = results.get("xsim_unknown")
                confirm_info: dict[str, Any] | None = None
                if xsim_result is not None and xsim_result["job"]["status"] == "done":
                    confirm_info = try_confirm_inferred_layout(client, xsim_result["evidence_id"])
                    print(f"demo: xsim_unknown inferred-layout confirm -> {confirm_info['status']}")
                    if confirm_info["status"] != "confirmed":
                        print(f"demo:   detail: {confirm_info.get('detail')}", file=sys.stderr)
                    else:
                        # Reindexed via the confirm-triggered
                        # parse_inferred_layout stage — re-summarize so the
                        # printed recordings/frame counts reflect it.
                        xsim_result["summary"] = summarize(
                            client, case_id, xsim_result["evidence_id"]
                        )
                        print(
                            "demo: xsim_unknown recordings after confirm: "
                            f"{xsim_result['summary']['recordings']}"
                        )

                # Report (signed PDF + BSA certificate) and one signed
                # export for the demo case (task B3), on the required
                # (hiksim_format) evidence's first live recording.
                report = get_or_create_report(client, case_id)
                report_sha256 = report["report_sha256"]
                print(
                    f"demo: report {report['id']}  pdf={report['pdf_path']}  "
                    f"report_sha256={report_sha256}"
                )
                print(f"demo: report certificate={report['certificate_path']}")

                required = results[REQUIRED_IMAGE]
                live_recording = pick_live_recording(client, case_id, required["evidence_id"])
                if live_recording is None:
                    print(
                        f"demo: no live recording found for {REQUIRED_IMAGE} — cannot export",
                        file=sys.stderr,
                    )
                    return 1
                export = get_or_create_export(client, case_id, live_recording["id"])
                export_content, verify_result = verify_export(client, export["id"])
                export_sha256 = hashlib.sha256(export_content).hexdigest()
                print(
                    f"demo: export {export['id']}  file={export['file_path']}  "
                    f"video_sha256={export_sha256}"
                )
                print(f"demo: export verify -> signature_valid={verify_result['signature_valid']}")
                if not verify_result["signature_valid"]:
                    print(
                        f"demo: exported file failed verification: {verify_result}",
                        file=sys.stderr,
                    )
                    return 1

            print(
                f"demo: OK — {REQUIRED_IMAGE} scanned with "
                f"{results[REQUIRED_IMAGE]['summary']['recordings']} recordings; "
                f"report {report['id']} generated; export {export['id']} verified valid."
            )
            return 0
        except DemoError as exc:
            print(f"demo: {exc}", file=sys.stderr)
            return 1
        except httpx.HTTPStatusError as exc:
            print(
                f"demo: HTTP {exc.response.status_code} on "
                f"{exc.request.method} {exc.request.url}\n{exc.response.text}",
                file=sys.stderr,
            )
            return 1
    finally:
        if args.keep_running:
            print(f"demo: --keep-running set; API left running at {base_url} (pid {proc.pid})")
        else:
            stop_api(proc)


if __name__ == "__main__":
    sys.exit(main())
