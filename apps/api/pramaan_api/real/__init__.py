"""Real (non-fixture) backing for cases, evidence, jobs, custody and
anchors (task B1, docs/02-BACKEND.md §3, §5-8).

Used by routers when ``Settings.stub_mode`` is ``False``. When it's
``True`` (the default — the Wave-0 demo path WEB builds against), routers
keep using ``pramaan_api.fixtures.store`` unchanged, per CLAUDE.md/
docs/PROMPTBOOK.md B1's "keep the demo fixtures working for routes you
don't replace yet" instruction.

Layout under ``Settings.data_dir`` (docs/02-BACKEND.md §3):

- ``app.db`` (via ``appdb.app_db``) — the case registry (``cases`` table).
  Seeded users' Ed25519 keys and the lab key live in ``keys/`` regardless
  of a DB row (see ``pramaan_custody.keys`` — used directly, keyed by
  username, no user table needed since the seeded 3 accounts are fixed).
- ``keys/<name>.ed25519`` — one file per examiner + the lab key, mode 600.
- ``cases/<case_id>/case.db`` — that case's ``evidence_images``, ``jobs``,
  ``audit_log``, ``anchors``, ``clock_observations`` (docs/01-FORENSIC-CORE.md
  §3.2/§3.4 schema, applied by ``pramaan_core.db.open_case``).
- ``cases/<case_id>/custody/chain.jsonl`` — append-only mirror of that
  case's ``audit_log``.
- ``anchors/ledger.jsonl`` — the shared ``LocalAnchor`` ledger (entries
  carry their own ``case_id``).
"""

from __future__ import annotations
