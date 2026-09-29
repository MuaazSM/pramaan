"""Filesystem layout helpers under ``Settings.data_dir`` (docs/02-BACKEND.md §3)."""

from __future__ import annotations

from pathlib import Path


def keys_dir(data_dir: str) -> Path:
    return Path(data_dir) / "keys"


def case_dir(data_dir: str, case_id: str) -> Path:
    return Path(data_dir) / "cases" / case_id


def cases_root(data_dir: str) -> Path:
    return Path(data_dir) / "cases"


def anchors_ledger_path(data_dir: str) -> Path:
    return Path(data_dir) / "anchors" / "ledger.jsonl"
