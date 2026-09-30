"""Small real-API HTTP client shared by ``tools/validate/validate.py``
(docs/05-INFRA-QA.md §5, task Q3).

Deliberately mirrors ``tools/demo/demo.py``'s pattern (login, CSRF
double-submit cookie, evidence registration, scan job polling): a black-box
client over plain HTTP, never importing API internals, so this exercises
the same contract a real caller would (CLAUDE.md rule 1/2 — only the API's
own ``pramaan_core.acquire`` path ever touches evidence bytes).
"""

from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

CSRF_COOKIE_NAME = "pramaan_csrf"
CSRF_HEADER_NAME = "x-csrf-token"


class ApiError(RuntimeError):
    """A validation/e2e-harness API interaction failed in a way worth a
    clean message instead of a raw traceback."""


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def tail(path: Path, n: int = 80) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return f"(could not read {path})"
    return "\n".join(lines[-n:])


def start_api(
    repo_root: Path,
    data_dir: Path,
    evidence_roots: list[Path],
    port: int,
    log_path: Path,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.Popen[bytes]:
    import json
    import os

    data_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PRAMAAN_DATA_DIR"] = str(data_dir)
    env["PRAMAAN_STUB_MODE"] = "0"
    env["PRAMAAN_EVIDENCE_ROOTS"] = json.dumps([str(p) for p in evidence_roots])
    env.setdefault("PRAMAAN_JOB_BACKEND", "inline")
    if extra_env:
        env.update(extra_env)
    log_file = log_path.open("wb")
    return subprocess.Popen(
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
        cwd=repo_root,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )


def wait_healthy(
    base_url: str, proc: subprocess.Popen[bytes], log_path: Path, deadline: float
) -> None:
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise ApiError(
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
    raise ApiError(
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
        raise ApiError("no CSRF cookie set — did login() run first?")
    return {CSRF_HEADER_NAME: token}


def login(client: httpx.Client, username: str = "examiner", password: str = "demo") -> None:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    if resp.status_code != 200:
        raise ApiError(f"login failed: {resp.status_code} {resp.text}")


def get_or_create_case(
    client: httpx.Client, case_number: str, title: str, lab: str
) -> dict[str, Any]:
    resp = client.get("/api/cases")
    resp.raise_for_status()
    for case in resp.json():
        if case["case_number"] == case_number:
            return dict(case)
    resp = client.post(
        "/api/cases",
        json={"case_number": case_number, "title": title, "fir_reference": None, "lab": lab},
        headers=csrf_headers(client),
    )
    if resp.status_code >= 400:
        raise ApiError(f"case creation failed: {resp.status_code} {resp.text}")
    return dict(resp.json())


def register_evidence(
    client: httpx.Client, case_id: str, image_path: Path, label: str, intake: dict[str, str]
) -> dict[str, Any]:
    resp = client.post(
        f"/api/cases/{case_id}/evidence",
        json={"path": str(image_path), "label": label, "intake": intake},
        headers=csrf_headers(client),
    )
    if resp.status_code >= 400:
        raise ApiError(f"registering {image_path} failed: {resp.status_code} {resp.text}")
    return dict(resp.json())


def run_job(client: httpx.Client, evidence_id: str, kind: str) -> dict[str, Any]:
    resp = client.post(
        f"/api/evidence/{evidence_id}/{kind}",
        json={},
        headers=csrf_headers(client),
    )
    if resp.status_code >= 400:
        raise ApiError(f"{kind} of {evidence_id} failed to queue: {resp.status_code} {resp.text}")
    return dict(resp.json())


def poll_job(client: httpx.Client, job_id: str, deadline: float) -> dict[str, Any]:
    while True:
        resp = client.get(f"/api/jobs/{job_id}")
        resp.raise_for_status()
        job = resp.json()
        if job["status"] in ("done", "failed"):
            return dict(job)
        if time.monotonic() > deadline:
            raise ApiError(f"job {job_id} did not finish before the timeout")
        time.sleep(0.5)


def get_json(client: httpx.Client, path: str, **params: Any) -> Any:
    resp = client.get(path, params=params)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


TOTAL_COUNT_HEADER = "X-Total-Count"


def get_json_with_total(client: httpx.Client, path: str, **params: Any) -> tuple[Any, int]:
    """Like :func:`get_json`, but also returns the *unpaginated* match count
    from the additive ``X-Total-Count`` response header (task FIX-1) — the
    500-row page cap on the body is unchanged. Falls back to ``len(body)``
    if the header is absent (e.g. stub mode, or an older API build)."""
    resp = client.get(path, params=params)
    if resp.status_code == 404:
        return None, 0
    resp.raise_for_status()
    body = resp.json()
    header = resp.headers.get(TOTAL_COUNT_HEADER)
    total = int(header) if header is not None else len(body)
    return body, total


def fetch_all_frames(
    client: httpx.Client, cases_path: str, *, channel: int, source: str, page_limit: int = 500
) -> tuple[list[dict[str, Any]], int, bool]:
    """Every frame for one ``(channel, source)`` combination on
    ``GET {cases_path}/frames``, walking multiple pages via a ``ts_header_us``
    cursor (``from``) when the true count exceeds ``page_limit`` (task
    FIX-1's ``X-Total-Count`` header makes the true count knowable; there is
    no offset/cursor param otherwise). Frames are deduplicated by
    ``payload_offset`` (harmless — the cursor is inclusive, to never skip
    rows tied at the same ``ts_header_us``).

    Returns ``(frames, total_count, truncated)``; ``truncated`` is true only
    if the server-reported total could not be fully retrieved (e.g. many
    frames share one ``ts_header_us`` and/or lack one entirely, which the
    ``from`` filter can't page past — docs/02-BACKEND.md §4's ``frm``
    clause excludes null-timestamp rows from any windowed page after the
    first).
    """
    collected: dict[int, dict[str, Any]] = {}
    cursor: int | None = None
    total = 0
    for _ in range(200):  # safety cap against a pathological non-advancing cursor
        params: dict[str, Any] = {"channel": channel, "source": source, "limit": page_limit}
        if cursor is not None:
            params["from"] = cursor
        page, total = get_json_with_total(client, f"{cases_path}/frames", **params)
        page = page or []
        for f in page:
            collected[f["payload_offset"]] = f
        if len(page) < page_limit:
            break
        last_ts = page[-1].get("ts_header_us")
        if last_ts is None or (cursor is not None and last_ts <= cursor):
            break
        cursor = last_ts
    return list(collected.values()), total, len(collected) < total
