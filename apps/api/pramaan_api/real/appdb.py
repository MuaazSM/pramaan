"""SQLite connection cache for the real backend.

Each distinct on-disk path (the app-level registry db, or one case's
``case.db``) gets one cached, thread-safe (``check_same_thread=False`` +
an explicit ``threading.Lock``) connection per process — FastAPI runs sync
route functions in a thread pool, so a bare ``sqlite3.connect`` per call
would violate SQLite's default same-thread rule, and unguarded concurrent
writers would race the custody chain's ``seq = MAX(seq) + 1``.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from pramaan_core.db import open_case

from pramaan_api.real.paths import case_dir


@dataclass
class GuardedDB:
    conn: sqlite3.Connection
    lock: threading.Lock


_dbs: dict[str, GuardedDB] = {}
_registry_lock = threading.Lock()


def _open(path: Path) -> GuardedDB:
    key = str(path.resolve())
    with _registry_lock:
        cached = _dbs.get(key)
        if cached is not None:
            return cached
        # Apply the canonical migration via pramaan_core.db, then reopen
        # with check_same_thread=False for the cached, lock-guarded handle.
        open_case(path).close()
        conn = sqlite3.connect(str(path / "case.db"), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # See pramaan_core.db.open_case's identical PRAGMA: this cached
        # connection is also reachable from a second, independent process
        # sharing the same data dir (task FIX-4 / FIX-2 #3).
        conn.execute("PRAGMA busy_timeout = 5000")
        guarded = GuardedDB(conn=conn, lock=threading.Lock())
        _dbs[key] = guarded
        return guarded


def app_db(data_dir: str) -> GuardedDB:
    return _open(Path(data_dir))


def case_db(data_dir: str, case_id: str) -> GuardedDB:
    return _open(case_dir(data_dir, case_id))


def reset_cache_for_tests() -> None:
    """Close and forget every cached connection. Only meaningful in tests
    that use a fresh ``tmp_path`` per test and want a clean slate — normal
    operation never needs this (each data_dir gets its own cache entries
    forever, which is correct for a long-running process).
    """
    with _registry_lock:
        for guarded in _dbs.values():
            guarded.conn.close()
        _dbs.clear()
