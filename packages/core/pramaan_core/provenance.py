"""``Provenance`` record helper (CLAUDE.md rule 4).

Every derived artefact must record how it was produced: parent SHA-256,
tool version, function name, parameters, UTC timestamp. This module is the
one place that fills in ``tool`` and ``tool_version`` consistently.
"""

from __future__ import annotations

from importlib import metadata
from typing import Any

from pramaan_core.models import Provenance
from pramaan_core.timeutil import utc_now_iso

TOOL_NAME = "pramaan"


def _tool_version() -> str:
    try:
        return metadata.version("pramaan-core")
    except metadata.PackageNotFoundError:
        # Not installed as a distribution (e.g. running straight from a
        # source checkout without `uv sync`) — fall back to a marker value
        # rather than fail; determinism only requires the *same* value
        # across a run, not a real semver here.
        return "0.0.0+unknown"


def make_provenance(
    step: str,
    params: dict[str, Any],
    parent_sha256: str | None = None,
    *,
    created_utc: str | None = None,
) -> Provenance:
    """Build a :class:`~pramaan_core.models.Provenance` record.

    ``step`` should be a dotted function path, e.g. ``"recovery.carve_annexb"``.
    ``params`` must already be JSON-serialisable — it is sorted wherever the
    record is persisted or hashed (``pramaan_core.ids.canonical_json``).
    ``created_utc`` defaults to now; pass a fixed value in tests that need a
    deterministic clock (it is excluded from content hashes regardless, per
    the model's docstring).
    """
    return Provenance(
        parent_sha256=parent_sha256,
        tool=TOOL_NAME,
        tool_version=_tool_version(),
        step=step,
        params=params,
        created_utc=created_utc or utc_now_iso(),
    )
