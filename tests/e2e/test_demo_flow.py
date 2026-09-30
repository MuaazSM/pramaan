"""``just demo`` smoke test (docs/05-INFRA-QA.md §6, task QD).

Drives ``tools/demo/demo.py`` (what ``just demo`` runs) as a real
subprocess against the real API in real mode, the same way a human running
``just demo`` would, and checks the documented acceptance criteria: it
exits 0 and its summary shows ``hiksim_format`` scanned with recordings
> 0; running it a second time also exits 0 (idempotent/resumable).

Marked ``slow`` — this starts a real ``uvicorn`` process, hashes the
corpus images, and runs the full scan pipeline (carve included), so it's
excluded from ``just check-qa``'s default ``-m "not slow"`` gate. Run
explicitly with ``uv run pytest tests/e2e -m slow``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_SCRIPT = REPO_ROOT / "tools" / "demo" / "demo.py"

# Generous per-run budget: corpus build (only if missing) + API boot + a
# full scan (hash, fingerprint, parse_index, carve, frame_index, clips,
# ...) on two real disk images.
_DEMO_TIMEOUT_S = 300.0
_SUBPROCESS_TIMEOUT_S = _DEMO_TIMEOUT_S + 60.0


def _run_demo() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "python", str(DEMO_SCRIPT), "--timeout", str(_DEMO_TIMEOUT_S)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
    )


def _assert_demo_ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, (
        f"tools/demo/demo.py exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert "hiksim_format" in result.stdout
    assert "job_status=done" in result.stdout
    assert "recordings: 0" not in result.stdout


@pytest.mark.slow
def test_demo_flow_scans_hiksim_format_end_to_end() -> None:
    """``just demo`` exits 0 and reports hiksim_format scanned, recordings > 0."""
    _assert_demo_ok(_run_demo())


@pytest.mark.slow
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group assumptions only")
def test_demo_flow_is_idempotent_on_rerun() -> None:
    """A second `just demo` run (same case, same content-derived evidence
    ids, resumable scan stages) must also exit 0 — docs/05-INFRA-QA.md §9
    ("`just demo` deterministic/idempotent").
    """
    _assert_demo_ok(_run_demo())
    _assert_demo_ok(_run_demo())
