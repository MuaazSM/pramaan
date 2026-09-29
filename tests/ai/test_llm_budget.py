"""Budget meter tests (docs/03-AI-TIMELINE.md §8.2/§9): caps, ``llm_calls``
rows, and hash-chained ``audit_log`` entries, against a real per-case SQLite
DB (schema from ``packages/core/pramaan_core/schema.sql``, via
``pramaan_core.db.open_case``).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pramaan_core.db as core_db
import pytest
from pramaan_core.ids import content_hash
from pramaan_llm.budget import (
    BudgetExceededError,
    BudgetMeter,
    actual_cost_usd,
    estimate_cost_usd,
    estimate_tokens,
)
from pramaan_llm.config import MODEL_CHEAP


def _insert_case(connection: sqlite3.Connection, case_id: str) -> None:
    """``llm_calls.case_id`` is a foreign key into ``cases`` (schema.sql) —
    insert a minimal case row so ``BudgetMeter.record`` can write rows for
    ``case_id`` in these tests."""
    with connection:
        connection.execute(
            """
            INSERT INTO cases (id, case_number, title, status, created_utc, updated_utc)
            VALUES (?, ?, ?, 'open', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """,
            (case_id, case_id, f"Test case {case_id}"),
        )


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = core_db.open_case(tmp_path / "case_test")
    for case_id in ("case_1", "case_a"):
        _insert_case(connection, case_id)
    yield connection
    connection.close()


def test_estimate_tokens_is_positive_and_monotonic() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 4) < estimate_tokens("a" * 400)


def test_estimate_cost_usd_scales_with_max_tokens() -> None:
    low = estimate_cost_usd(model=MODEL_CHEAP, system="s", messages=[], max_tokens=100)
    high = estimate_cost_usd(model=MODEL_CHEAP, system="s", messages=[], max_tokens=100_000)
    assert high > low


def test_actual_cost_usd_discounts_cache_reads() -> None:
    full_price = actual_cost_usd(
        model=MODEL_CHEAP, input_tokens=1000, output_tokens=0, cache_read_input_tokens=0
    )
    with_cache = actual_cost_usd(
        model=MODEL_CHEAP, input_tokens=1000, output_tokens=0, cache_read_input_tokens=1000
    )
    assert with_cache < full_price


def test_check_passes_under_cap(conn: sqlite3.Connection) -> None:
    meter = BudgetMeter(conn, cap_total_usd=60.0, cap_case_usd=5.0)
    meter.check("case_1", 0.01)  # must not raise


def test_check_raises_over_per_case_cap(conn: sqlite3.Connection) -> None:
    meter = BudgetMeter(conn, cap_total_usd=60.0, cap_case_usd=1.0)
    with pytest.raises(BudgetExceededError) as excinfo:
        meter.check("case_1", 2.0)
    assert excinfo.value.scope == "case"


def test_check_raises_over_total_cap(conn: sqlite3.Connection) -> None:
    meter = BudgetMeter(conn, cap_total_usd=1.0, cap_case_usd=60.0)
    with pytest.raises(BudgetExceededError) as excinfo:
        meter.check("case_1", 2.0)
    assert excinfo.value.scope == "total"


def test_record_writes_one_llm_calls_row(conn: sqlite3.Connection) -> None:
    meter = BudgetMeter(conn)
    record = meter.record(
        case_id="case_1",
        feature="assistant.query",
        provider="fixture",
        model=MODEL_CHEAP,
        input_tokens=100,
        output_tokens=20,
        cache_read_input_tokens=0,
        request_sha256="a" * 64,
        response_sha256="b" * 64,
        actor="examiner",
        now_utc="2026-03-12T10:00:00+00:00",
    )
    rows = conn.execute("SELECT * FROM llm_calls WHERE id = ?", (record.id,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["case_id"] == "case_1"
    assert rows[0]["cost_usd"] == pytest.approx(record.cost_usd)


def test_record_appends_one_hash_chained_audit_entry(conn: sqlite3.Connection) -> None:
    meter = BudgetMeter(conn)
    meter.record(
        case_id="case_1",
        feature="assistant.query",
        provider="fixture",
        model=MODEL_CHEAP,
        input_tokens=100,
        output_tokens=20,
        cache_read_input_tokens=0,
        request_sha256="a" * 64,
        response_sha256="b" * 64,
        actor="examiner",
        now_utc="2026-03-12T10:00:00+00:00",
    )
    row = conn.execute("SELECT * FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
    assert row["action"] == "llm_call"
    assert row["prev_hash"] is None  # first entry in a fresh DB
    unsigned = {
        "seq": row["seq"],
        "prev_hash": row["prev_hash"],
        "ts_utc": row["ts_utc"],
        "actor": row["actor"],
        "role": row["role"],
        "action": row["action"],
        "object_type": row["object_type"],
        "object_id": row["object_id"],
        "payload_sha256": row["payload_sha256"],
        "details": json.loads(row["details"]),
    }
    assert row["entry_hash"] == content_hash(unsigned)


def test_second_record_chains_to_the_first(conn: sqlite3.Connection) -> None:
    meter = BudgetMeter(conn)
    for i in range(2):
        meter.record(
            case_id="case_1",
            feature="assistant.query",
            provider="fixture",
            model=MODEL_CHEAP,
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=0,
            request_sha256=f"{i}" * 64,
            response_sha256=f"{i}" * 64,
            actor="examiner",
            now_utc=f"2026-03-12T10:0{i}:00+00:00",
        )
    rows = conn.execute("SELECT seq, prev_hash, entry_hash FROM audit_log ORDER BY seq").fetchall()
    assert len(rows) == 2
    assert rows[0]["prev_hash"] is None
    assert rows[1]["prev_hash"] == rows[0]["entry_hash"]


def test_spent_case_usd_only_counts_that_case(conn: sqlite3.Connection) -> None:
    meter = BudgetMeter(conn)
    meter.record(
        case_id="case_a",
        feature="assistant.query",
        provider="fixture",
        model=MODEL_CHEAP,
        input_tokens=1000,
        output_tokens=1000,
        cache_read_input_tokens=0,
        request_sha256="a" * 64,
        response_sha256="a" * 64,
        actor="examiner",
        now_utc="2026-03-12T10:00:00+00:00",
    )
    assert meter.spent_case_usd("case_b") == 0.0
    assert meter.spent_case_usd("case_a") > 0.0
    assert meter.spent_total_usd() == pytest.approx(meter.spent_case_usd("case_a"))


def test_calls_are_blocked_once_the_per_case_cap_is_reached(conn: sqlite3.Connection) -> None:
    """docs/03-AI-TIMELINE.md §9: "Calls blocked beyond per-case and total caps"."""
    meter = BudgetMeter(conn, cap_total_usd=60.0, cap_case_usd=0.0001)
    meter.record(
        case_id="case_1",
        feature="assistant.query",
        provider="fixture",
        model=MODEL_CHEAP,
        input_tokens=1000,
        output_tokens=1000,
        cache_read_input_tokens=0,
        request_sha256="a" * 64,
        response_sha256="a" * 64,
        actor="examiner",
        now_utc="2026-03-12T10:00:00+00:00",
    )
    with pytest.raises(BudgetExceededError):
        meter.check("case_1", 0.0001)
