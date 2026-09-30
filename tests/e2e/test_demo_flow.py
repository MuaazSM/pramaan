"""``just demo`` smoke test (docs/05-INFRA-QA.md §6, tasks QD/FIX-2).

Drives ``tools/demo/demo.py`` (what ``just demo`` runs) as a real
subprocess against the real API in real mode, the same way a human running
``just demo`` would, and checks the documented acceptance criteria: it
exits 0; its summary shows ``hiksim_format``/``dhsim_format`` scanned with
recordings > 0 (``STRICT_IMAGES``), ``hwsim_format``/``xsim_unknown``
attempted and reported (``BEST_EFFORT_IMAGES`` — see ``tools/demo/demo.py``
for why those two are best-effort rather than hard-gated today); a report
PDF path + ``report_sha256``; and a signed export that verifies valid.
Running it a second time also exits 0 (idempotent/resumable).

Marked ``slow`` — this starts a real ``uvicorn`` process, hashes the
corpus images, and runs the full scan pipeline (carve, report, export
included) on four real disk images, so it's excluded from
``just check-qa``'s default ``-m "not slow"`` gate. Run explicitly with
``uv run pytest tests/e2e -m slow``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_SCRIPT = REPO_ROOT / "tools" / "demo" / "demo.py"

# Generous per-run budget: corpus build (only if missing) + API boot + a
# full scan (hash, fingerprint, parse_index, carve, frame_index, clips,
# ...) on four real disk images, plus report + export generation.
_DEMO_TIMEOUT_S = 500.0
_SUBPROCESS_TIMEOUT_S = _DEMO_TIMEOUT_S + 60.0


def _run_demo() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "python", str(DEMO_SCRIPT), "--timeout", str(_DEMO_TIMEOUT_S)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
    )


def _image_block(stdout: str, name: str) -> str:
    """The ``[name]  evidence_id=...`` section of the printed summary, up
    to (but not including) the next blank line — isolates one image's
    ``recordings: N`` line from every other image's, so a *different*
    image's ``recordings: 0`` (e.g. ``xsim_unknown`` before its inferred
    layout is confirmed, or a best-effort image's failed scan) can never
    be mistaken for this one's.
    """
    match = re.search(rf"\[{re.escape(name)}\].*?(?=\n\n)", stdout, re.DOTALL)
    assert match is not None, f"no [{name}] section in stdout:\n{stdout}"
    return match.group(0)


def _assert_demo_ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, (
        f"tools/demo/demo.py exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    stdout = result.stdout

    # STRICT_IMAGES: must have scanned to completion with recordings > 0.
    for name in ("hiksim_format", "dhsim_format"):
        block = _image_block(stdout, name)
        assert "job_status=done" in block, block
        assert "recordings: 0" not in block, block

    # BEST_EFFORT_IMAGES: always attempted and reported, whatever the
    # outcome (tools/demo/demo.py's BEST_EFFORT_IMAGES docstring explains
    # why hwsim_format/xsim_unknown aren't hard-gated here).
    for name in ("hwsim_format", "xsim_unknown"):
        assert f"[{name}]" in stdout, stdout

    # Report + signed export (task B3 routes), per FIX-2's acceptance
    # criteria: a report PDF path + report_sha256, and an export that
    # verifies valid.
    assert re.search(r"demo: report rpt_\S+\s+pdf=\S+\.pdf\s+report_sha256=[0-9a-f]+", stdout), (
        stdout
    )
    assert "demo: export verify -> signature_valid=True" in stdout, stdout


@pytest.mark.slow
def test_demo_flow_scans_the_demo_case_end_to_end() -> None:
    """``just demo`` exits 0; hiksim_format/dhsim_format scan with
    recordings > 0; hwsim_format/xsim_unknown are attempted and reported;
    a report and a verified signed export are produced.
    """
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
