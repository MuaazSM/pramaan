"""Shared fixtures for the API e2e suite (docs/05-INFRA-QA.md §6, task Q3).

Boots one real API subprocess (``PRAMAAN_STUB_MODE=0``) for the whole e2e
session, the same black-box, real-HTTP way ``tools/demo/demo.py`` and
``tools/validate/validate.py`` do (never importing API internals — CLAUDE.md
rule 1/2: only the API's own ``pramaan_core.acquire`` path touches evidence
bytes). A second evidence root under ``data/e2e/tamper_root`` holds writable
*copies* of corpus images for the tamper tests, so no corpus fixture under
``corpus/images`` is ever modified in place.

Everything here is marked ``slow`` by the tests that use it (real scans on
real images) — excluded from ``just check-qa``'s default gate, run
explicitly by ``just e2e``.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_IMAGES = REPO_ROOT / "corpus" / "images"
DATA_DIR = REPO_ROOT / "data" / "e2e"
TAMPER_ROOT = DATA_DIR / "tamper_root"

sys.path.insert(0, str(REPO_ROOT / "tools" / "validate"))
import api_client as api  # noqa: E402

CASE_LAB = "Pramaan Digital Forensics Lab (e2e)"

INTAKE_BY_IMAGE: dict[str, dict[str, str]] = {
    "hiksim_format": {
        "seized_at_local": "2026-03-12T16:40:00+05:30",
        "dvr_displayed_time": "2026-03-12T16:41:40",
        "reference_time": "2026-03-12T16:36:28+05:30",
    },
    "hiksim_clean": {
        "seized_at_local": "2026-03-12T16:30:24+05:30",
        "dvr_displayed_time": "2026-03-12T16:35:36",
        "reference_time": "2026-03-12T16:30:24+05:30",
    },
    "xsim_unknown": {
        "seized_at_local": "2026-03-12T16:31:14+05:30",
        "dvr_displayed_time": "2026-03-12T16:36:26",
        "reference_time": "2026-03-12T16:31:14+05:30",
    },
}
_INTAKE_EXTRAS = {
    "reference_source": "NTP phone clock",
    "timezone": "Asia/Kolkata",
    "write_blocker": "Tableau T35u",
    "notes": "tests/e2e fixture",
}


def intake_for(image: str) -> dict[str, str]:
    return {**INTAKE_BY_IMAGE[image], **_INTAKE_EXTRAS}


@dataclass
class RealApi:
    base_url: str
    data_dir: Path
    tamper_root: Path

    def case_db_path(self, case_id: str) -> Path:
        return self.data_dir / "cases" / case_id / "case.db"


@pytest.fixture()
def real_api() -> Iterator[RealApi]:
    """Function-scoped (fresh API subprocess + empty data dir) per test —
    deliberately NOT session-shared. A discovered BACKEND bug
    (`apps/api/pramaan_api/real/store.py::_find_case_for_evidence` resolves
    a content-derived evidence_id to whichever case *sorts first*, not the
    case it was registered under — see docs/progress/Q3.md and
    docs/VALIDATION.md "Cross-workstream issues") means two tests sharing
    one data dir and registering the *same* corpus image (byte-identical
    content -> identical evidence_id) into different cases would silently
    cross-contaminate each other's scans. Isolating each test's data dir
    sidesteps that pre-existing bug rather than letting these tests become
    flaky/misleading about what they're actually testing.
    """
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    TAMPER_ROOT.mkdir(parents=True, exist_ok=True)

    port = api.free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_path = DATA_DIR / "api.log"
    proc = api.start_api(REPO_ROOT, DATA_DIR, [CORPUS_IMAGES, TAMPER_ROOT], port, log_path)
    deadline = time.monotonic() + 120.0
    try:
        api.wait_healthy(base_url, proc, log_path, deadline)
        yield RealApi(base_url=base_url, data_dir=DATA_DIR, tamper_root=TAMPER_ROOT)
    finally:
        api.stop_api(proc)


@pytest.fixture()
def client(real_api: RealApi) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=real_api.base_url, timeout=60.0) as c:
        api.login(c)
        yield c


def create_case(client: httpx.Client, case_number: str) -> dict[str, Any]:
    return api.get_or_create_case(client, case_number, case_number, CASE_LAB)


def register_and_scan(
    client: httpx.Client, case_id: str, image_path: Path, deadline: float
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Register ``image_path`` under ``case_id`` and run+wait its scan job."""
    intake = (
        intake_for(image_path.stem)
        if image_path.stem in INTAKE_BY_IMAGE
        else {
            **{
                "seized_at_local": "2026-03-12T16:30:00+05:30",
                "dvr_displayed_time": "2026-03-12T16:35:00",
                "reference_time": "2026-03-12T16:30:00+05:30",
            },
            **_INTAKE_EXTRAS,
        }
    )
    evidence = api.register_evidence(client, case_id, image_path, f"e2e: {image_path.name}", intake)
    job = api.run_job(client, evidence["id"], "scan")
    job = api.poll_job(client, job["id"], deadline)
    return evidence, job


def flip_one_byte(path: Path, offset: int = 4096) -> None:
    data = bytearray(path.read_bytes())
    off = offset % len(data)
    data[off] ^= 0xFF
    path.write_bytes(bytes(data))


def tamper_audit_entry(db_path: Path, seq: int) -> None:
    """Directly corrupt one custody entry's ``action`` field, simulating a
    tampered/corrupted audit database — the thing ``GET
    /cases/{cid}/audit/verify`` (packages/custody/pramaan_custody
    /chain_verify.py) exists to catch. Never touches an evidence image
    (CLAUDE.md rule 1/2) — this is the app's own SQLite state, not evidence.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("UPDATE audit_log SET action = 'tampered.action' WHERE seq = ?", (seq,))
        conn.commit()
    finally:
        conn.close()
