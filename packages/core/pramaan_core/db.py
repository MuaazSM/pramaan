"""SQLite case database: schema application, migrations, ``open_case``.

One database per case at ``<case_dir>/case.db`` (docs/01-FORENSIC-CORE.md
§3.2/§3.4). Migrations are tracked with ``PRAGMA user_version`` so re-opening
an existing case is idempotent and safe to run from every workstream.
"""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

#: Bump when a new migration step is added below.
SCHEMA_VERSION = 1


def _schema_sql() -> str:
    return resources.files("pramaan_core").joinpath("schema.sql").read_text(encoding="utf-8")


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply migrations up to :data:`SCHEMA_VERSION`.

    Migration 1 creates the full baseline schema (``schema.sql``). Future
    migrations must be additive (new tables / nullable or defaulted
    columns) per CLAUDE.md's shared-contract rule — never drop or rename a
    column another workstream already depends on.
    """
    row = conn.execute("PRAGMA user_version").fetchone()
    version: int = row[0]
    if version < 1:
        conn.executescript(_schema_sql())
        conn.execute("PRAGMA user_version = 1")
        version = 1
    conn.commit()


def open_case(case_dir: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) ``<case_dir>/case.db``, applying migrations.

    Creates ``case_dir`` if it does not exist. Returns a connection with
    foreign keys enabled and a ``Row`` row factory (``row["col"]`` access).
    The caller owns the connection's lifetime and must close it.
    """
    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    db_path = case_dir / "case.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    return conn
