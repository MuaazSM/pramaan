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
   already exists), registers each demo evidence image via
   ``POST /cases/{cid}/evidence`` (never opens/copies the image itself —
   CLAUDE.md rule 1/2: only the API's own ``pramaan_core.acquire`` path
   touches evidence bytes), runs the full scan pipeline job on each, and
   waits for completion by polling ``GET /jobs/{jid}``.
4. Prints a summary (recordings, recovered/deleted frames, stage
   statuses) per evidence image.
5. Stops the API subprocess, unless ``--keep-running`` was passed.

Idempotent and safe to re-run: case lookup is by ``case_number``, evidence
ids are content-derived (registering the same image twice is a no-op), and
scan stages are resumable (a second scan on the same evidence skips every
stage via its input-hash marker) — see ``docs/progress/B1.md``/``B2.md``.

Usage::

    uv run python tools/demo/demo.py [--keep-running] [--timeout SECONDS] [--port PORT]

Exits 0 on success (hiksim_format scanned, status "done", recordings > 0);
non-zero otherwise, with a message on stderr.
"""

from __future__ import annotations

import argparse
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
# demo (e.g. xsim_unknown / hwsim_format once their pipeline stages are
# wired) — nothing else in this script needs to change.
DEMO_EVIDENCE: list[tuple[str, str]] = [
    ("hiksim_format", "DVR HDD, shop front, seized 12 Mar (Hikvision-format, deleted footage)"),
    ("dhsim_format", "DVR HDD, second unit (Dahua-format, deleted footage)"),
]

# The image that the Wave 2 gate cares about — its scan must succeed with
# recordings > 0 for `just demo` to exit 0.
REQUIRED_IMAGE = "hiksim_format"

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
    requests = [{"channel": c} for c in channels] or [{}]
    for extra_params in requests:
        resp = client.get(
            f"/api/cases/{case_id}/frames",
            params={"source": "carved", "limit": 500, **extra_params},
        )
        resp.raise_for_status()
        page = resp.json()
        if len(page) >= 500:
            truncated = True
        carved_count += sum(1 for f in page if f["image_id"] == evidence_id)

    return {
        "recordings": len(recordings),
        "recovered_frames": carved_count,
        "recovered_frames_truncated": truncated,
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

                results: dict[str, dict[str, Any]] = {}
                for name, label in DEMO_EVIDENCE:
                    image_path = CORPUS_IMAGES / f"{name}.img"
                    if not image_path.exists():
                        print(
                            f"demo: skipping {name} — {image_path} not found in corpus",
                            file=sys.stderr,
                        )
                        continue
                    evidence = register_evidence(client, case_id, image_path, label)
                    evidence_id = evidence["id"]
                    print(f"demo: registered {name} -> evidence_id={evidence_id}")
                    job = run_scan(client, evidence_id)
                    print(f"demo: scanning {name} (job {job['id']}) ...")
                    job = poll_job(client, job["id"], deadline)
                    summary = summarize(client, case_id, evidence_id)
                    results[name] = {"evidence_id": evidence_id, "job": job, "summary": summary}

                print_summary(results)

                required = results.get(REQUIRED_IMAGE)
                if required is None:
                    print(f"demo: {REQUIRED_IMAGE} was never scanned", file=sys.stderr)
                    return 1
                if required["job"]["status"] != "done":
                    print(
                        f"demo: {REQUIRED_IMAGE} scan did not finish successfully "
                        f"(status={required['job']['status']})",
                        file=sys.stderr,
                    )
                    return 1
                if required["summary"]["recordings"] <= 0:
                    print(
                        f"demo: {REQUIRED_IMAGE} scanned but produced 0 recordings", file=sys.stderr
                    )
                    return 1

            print(f"demo: OK — {REQUIRED_IMAGE} scanned with "
                  f"{results[REQUIRED_IMAGE]['summary']['recordings']} recordings.")
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
