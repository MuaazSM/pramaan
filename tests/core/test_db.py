"""Case DB migration tests: `open_case` creates the schema and is idempotent."""

from __future__ import annotations

from pathlib import Path

from pramaan_core.db import SCHEMA_VERSION, open_case

EXPECTED_TABLES = {
    "cases",
    "examiners",
    "evidence_images",
    "scan_runs",
    "vendor_matches",
    "recordings",
    "clips",
    "deletion_findings",
    "log_events",
    "inferred_layouts",
    "clock_models",
    "motion_segments",
    "detections",
    "reports",
    "exports",
    "audit_log",
    "anchors",
    "llm_calls",
    "jobs",
}


def test_open_case_creates_expected_tables(tmp_path: Path) -> None:
    case_dir = tmp_path / "case1"
    conn = open_case(case_dir)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        names = {row["name"] for row in rows}
        assert EXPECTED_TABLES <= names
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert (case_dir / "case.db").exists()
    finally:
        conn.close()


def test_open_case_is_idempotent_and_preserves_data(tmp_path: Path) -> None:
    case_dir = tmp_path / "case2"

    conn1 = open_case(case_dir)
    conn1.execute(
        "INSERT INTO cases (id, case_number, title, status, created_utc, updated_utc) "
        "VALUES ('c1', 'CR-2026-0001', 'Test case', 'open', 't0', 't0')"
    )
    conn1.commit()
    conn1.close()

    conn2 = open_case(case_dir)
    try:
        row = conn2.execute("SELECT title FROM cases WHERE id = 'c1'").fetchone()
        assert row is not None
        assert row["title"] == "Test case"
        assert conn2.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        conn2.close()


def test_foreign_keys_enabled(tmp_path: Path) -> None:
    conn = open_case(tmp_path / "case3")
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_audit_log_seq_is_unique(tmp_path: Path) -> None:
    conn = open_case(tmp_path / "case4")
    try:
        conn.execute(
            "INSERT INTO audit_log (id, seq, prev_hash, entry_hash, ts_utc, actor, role, "
            "action, object_type, object_id, details, signature) VALUES "
            "('h1', 1, NULL, 'h1', 't0', 'examiner1', 'examiner', 'evidence.registered', "
            "'evidence_image', 'img_1', '{}', 'sig1')"
        )
        conn.commit()
        row = conn.execute("SELECT seq FROM audit_log WHERE id = 'h1'").fetchone()
        assert row["seq"] == 1
    finally:
        conn.close()
