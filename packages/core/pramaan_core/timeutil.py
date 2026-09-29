"""UTC timestamp helper.

Single source of truth for the ISO-8601 strings used in ``acquired_utc``,
``created_utc`` and similar fields. These are wall-clock values, so
CLAUDE.md rule 5 requires them to be excluded from any content hash — callers
that hash a model must drop or override this field first (see
``Provenance.created_utc`` docstring in ``pramaan_core.models``).
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now_iso() -> str:
    """Current UTC time as ISO-8601 with a ``Z`` suffix, microsecond precision."""
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
