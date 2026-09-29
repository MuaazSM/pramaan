"""Deterministic OpenAPI export (docs/02-BACKEND.md §4: "exported to
``apps/api/openapi.json`` on every ``just check``").

    uv run python apps/api/pramaan_api/openapi_export.py          # write
    uv run python apps/api/pramaan_api/openapi_export.py --check  # verify, no write

Determinism (CLAUDE.md rule 5): ``json.dumps(..., sort_keys=True)`` plus a
trailing newline, so re-running on an unchanged app produces byte-identical
output. ``just check-backend`` runs the ``--check`` form and fails the gate
if ``apps/api/openapi.json`` is stale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pramaan_api.main import app

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "openapi.json"


def render() -> str:
    schema = app.openapi()
    return json.dumps(schema, sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def main(argv: list[str]) -> int:
    rendered = render()
    check_only = "--check" in argv
    if check_only:
        if not OUTPUT_PATH.exists():
            msg = f"{OUTPUT_PATH} does not exist — run without --check to generate it."
            print(msg, file=sys.stderr)
            return 1
        current = OUTPUT_PATH.read_text(encoding="utf-8")
        if current != rendered:
            msg = f"{OUTPUT_PATH} is stale — run 'uv run python {__file__}' to regenerate."
            print(msg, file=sys.stderr)
            return 1
        print(f"{OUTPUT_PATH} is up to date.")
        return 0
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
