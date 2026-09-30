"""Real (non-fixture) data access for recordings, frames, prove-it hex,
thumbnails, clips, log events, deletions and search (task B2,
docs/02-BACKEND.md §4).

Mirrors ``pramaan_api.fixtures.store``'s function shapes so routers branch
on ``settings.stub_mode`` the same way B1's cases/evidence/jobs routes do
(``pramaan_api.routers.evidence``). A frame only carries an ``image_id``
(never a ``case_id``), so every frame/clip lookup here resolves the owning
case first by scanning ``cases_root`` — fine at this demo's scale (a
handful of cases), matching ``pramaan_api.real.store._find_case_for_evidence``.

Every evidence byte is read through ``pramaan_core.evidence.EvidenceReader``
(CLAUDE.md rule 2); derived files (clips, thumbnails) are plain files this
module reads/writes directly under ``<case_dir>/derived/`` — never under an
evidence path.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import duckdb
from pramaan_core.evidence import EvidenceReader
from pramaan_core.models import (
    DeletionFinding,
    FrameRef,
    InferredField,
    InferredLayout,
    LogEvent,
    Recording,
    VendorMatch,
)

from pramaan_api.real import appdb
from pramaan_api.real import store as real_store
from pramaan_api.real.paths import case_dir
from pramaan_api.schemas import SearchResult
from pramaan_api.security import User

_FRAME_COLUMNS: tuple[str, ...] = tuple(FrameRef.model_fields.keys())
_FRAME_SELECT = ", ".join(_FRAME_COLUMNS)
_THUMB_TIMEOUT_S = 30


# --- frame index (DuckDB over the Parquet index) ----------------------------


def _frames_glob(cdir: Path) -> str:
    return str(cdir / "index" / "frames-*.parquet")


def _existing_frame_columns(con: duckdb.DuckDBPyConnection) -> set[str]:
    """Column names actually present in the ``frames`` view (task FIX-4:
    ``DESCRIBE`` the *live* Parquet schema rather than assuming every
    :class:`FrameRef` field is there — a frame-index file written before
    FIX-3 added ``payload_sha256`` has no such column, and a case dir can
    mix old- and new-schema per-image files after an upgrade)."""
    return {row[0] for row in con.execute("DESCRIBE frames").fetchall()}


def _frame_select_list(existing: set[str]) -> str:
    """The ``_FRAME_COLUMNS`` select list, substituting a typed ``NULL``
    for any column the on-disk schema doesn't have (task FIX-4). Every
    such field is optional on :class:`FrameRef` (e.g. ``payload_sha256``),
    so ``NULL`` round-trips to ``None`` there instead of DuckDB raising
    ``BinderException: Referenced column ... not found``.
    """
    return ", ".join(col if col in existing else f"NULL AS {col}" for col in _FRAME_COLUMNS)


def _query_frames(
    cdir: Path,
    *,
    where: str = "",
    params: list[Any] | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """Run a parameterised SELECT over every ``frames-*.parquet`` under
    ``cdir``, returning only :class:`FrameRef`'s own columns (the four
    AI-filled timeline columns are excluded — ``FrameRef`` is
    ``extra="forbid"``). Returns ``[]`` when the case has no frame index
    yet, rather than letting DuckDB error on an empty glob.

    Schema-tolerant (task FIX-4): a column present in the current
    :class:`FrameRef` but missing from an older on-disk Parquet file (or
    from *some* of the per-image files under this case, if it was scanned
    across an upgrade) is selected as ``NULL`` rather than erroring —
    ``union_by_name=true`` lets the glob itself mix files with different
    columns, and :func:`_frame_select_list` covers the case where a
    column is missing from *every* file in the glob (``union_by_name``
    alone can't invent a column no file has at all).

    ``offset`` (task FIX-4, Q3's validation run: generic-carved frames —
    e.g. XSIM's blind carve pass — legitimately have no ``ts_header_us``,
    which made the ``from``/``to`` query params useless as a de-facto
    pagination cursor for them, since ``_frame_filter_clauses`` correctly
    excludes NULL-timestamp rows from any ``ts_header_us``-range filter).
    ``ORDER BY channel, ts_header_us, payload_offset`` is a genuine total
    order over every row regardless of ``ts_header_us`` being NULL —
    DuckDB sorts NULLs last, deterministically, for a fixed ``ORDER BY``
    (confirmed directly) — so a plain, stable ``LIMIT/OFFSET`` over that
    same order reaches every row, timestamped or not.
    """
    if not any(cdir.glob("index/frames-*.parquet")):
        return []
    con = duckdb.connect(":memory:")
    try:
        con.execute(
            f"CREATE VIEW frames AS SELECT * FROM read_parquet("
            f"'{_frames_glob(cdir)}', union_by_name=true)"
        )
        existing = _existing_frame_columns(con)
        sql = f"SELECT {_frame_select_list(existing)} FROM frames"
        if where:
            sql += f" WHERE {where}"
        sql += " ORDER BY channel, ts_header_us, payload_offset"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        if offset:
            sql += f" OFFSET {int(offset)}"
        rows = con.execute(sql, params or []).fetchall()
        cols = [d[0] for d in con.description] if con.description else []
        return [dict(zip(cols, row, strict=True)) for row in rows]
    finally:
        con.close()


def _frame_filter_clauses(
    *,
    channel: int | None,
    source: str | None,
    deleted: bool | None,
    frame_type: str | None,
    frm: int | None,
    to: int | None,
    recording_id: str | None,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if recording_id is not None:
        clauses.append("recording_id = ?")
        params.append(recording_id)
    if channel is not None:
        clauses.append("channel = ?")
        params.append(channel)
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if deleted is not None:
        clauses.append("deleted = ?")
        params.append(deleted)
    if frame_type is not None:
        clauses.append("frame_type = ?")
        params.append(frame_type)
    if frm is not None:
        clauses.append("(ts_header_us IS NOT NULL AND ts_header_us >= ?)")
        params.append(frm)
    if to is not None:
        clauses.append("(ts_header_us IS NOT NULL AND ts_header_us <= ?)")
        params.append(to)
    return clauses, params


def list_frames(
    data_dir: str,
    case_id: str,
    *,
    channel: int | None = None,
    source: str | None = None,
    deleted: bool | None = None,
    frame_type: str | None = None,
    frm: int | None = None,
    to: int | None = None,
    recording_id: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[FrameRef]:
    """``offset`` (task FIX-4) pages over the deterministic total order
    (``channel``, ``ts_header_us``, ``payload_offset``) regardless of
    ``ts_header_us`` being present — see :func:`_query_frames`'s own
    docstring for why this is needed alongside (not instead of) the
    ``frm``/``to`` timestamp-range filters, which are unchanged.
    """
    clauses, params = _frame_filter_clauses(
        channel=channel,
        source=source,
        deleted=deleted,
        frame_type=frame_type,
        frm=frm,
        to=to,
        recording_id=recording_id,
    )
    rows = _query_frames(
        case_dir(data_dir, case_id),
        where=" AND ".join(clauses),
        params=params,
        limit=limit,
        offset=offset,
    )
    return [FrameRef(**row) for row in rows]


def count_frames(
    data_dir: str,
    case_id: str,
    *,
    channel: int | None = None,
    source: str | None = None,
    deleted: bool | None = None,
    frame_type: str | None = None,
    frm: int | None = None,
    to: int | None = None,
    recording_id: str | None = None,
) -> int:
    """The *unpaginated* count of frames matching the same filters
    :func:`list_frames` accepts (task FIX-1: ``GET /cases/{cid}/frames``'s
    additive ``X-Total-Count`` response header — the 500-row page cap on
    the body is unchanged, this only tells a client the true total)."""
    cdir = case_dir(data_dir, case_id)
    if not any(cdir.glob("index/frames-*.parquet")):
        return 0
    clauses, params = _frame_filter_clauses(
        channel=channel,
        source=source,
        deleted=deleted,
        frame_type=frame_type,
        frm=frm,
        to=to,
        recording_id=recording_id,
    )
    con = duckdb.connect(":memory:")
    try:
        con.execute(
            f"CREATE VIEW frames AS SELECT * FROM read_parquet("
            f"'{_frames_glob(cdir)}', union_by_name=true)"
        )
        sql = "SELECT COUNT(*) FROM frames"
        if clauses:
            sql += f" WHERE {' AND '.join(clauses)}"
        row = con.execute(sql, params).fetchone()
        return int(row[0]) if row is not None else 0
    finally:
        con.close()


def get_frame_with_case(data_dir: str, frame_id: str) -> tuple[str, FrameRef] | None:
    for cid in real_store.iter_case_ids(data_dir):
        rows = _query_frames(
            case_dir(data_dir, cid), where="frame_id = ?", params=[frame_id], limit=1
        )
        if rows:
            return cid, FrameRef(**rows[0])
    return None


def get_frame(data_dir: str, frame_id: str) -> FrameRef | None:
    found = get_frame_with_case(data_dir, frame_id)
    return found[1] if found is not None else None


# --- recordings --------------------------------------------------------


def _row_to_recording(row: Any) -> Recording:
    from pramaan_core.models import ByteRange

    return Recording(
        id=row["id"],
        image_id=row["image_id"],
        channel=row["channel"],
        stream=row["stream"],
        start_ts_us=row["start_ts_us"],
        end_ts_us=row["end_ts_us"],
        byte_ranges=[ByteRange(**br) for br in json.loads(row["byte_ranges"])],
        source=row["source"],
        deleted=bool(row["deleted"]),
    )


def list_recordings(
    data_dir: str,
    case_id: str,
    *,
    channel: int | None = None,
    source: str | None = None,
    deleted: bool | None = None,
    frm: int | None = None,
    to: int | None = None,
) -> list[Recording]:
    conn = appdb.case_db(data_dir, case_id).conn
    clauses = ["image_id IN (SELECT id FROM evidence_images WHERE case_id = ?)"]
    params: list[Any] = [case_id]
    if channel is not None:
        clauses.append("channel = ?")
        params.append(channel)
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if deleted is not None:
        clauses.append("deleted = ?")
        params.append(int(deleted))
    rows = conn.execute(
        f"SELECT * FROM recordings WHERE {' AND '.join(clauses)} ORDER BY channel, start_ts_us",
        params,
    ).fetchall()
    out = [_row_to_recording(r) for r in rows]
    if frm is not None:
        out = [r for r in out if r.end_ts_us is None or r.end_ts_us >= frm]
    if to is not None:
        out = [r for r in out if r.start_ts_us is None or r.start_ts_us <= to]
    return out


def get_recording(data_dir: str, recording_id: str) -> Recording | None:
    """Cross-case lookup — only correct when the caller genuinely has no
    case_id of its own (task FIX-4: see :func:`get_recording_in_case` for
    the case-scoped counterpart every caller that *does* have one, e.g. an
    export, must use instead — a ``recording_id`` is a stable hash of
    ``(image_id, channel, start, offset)``, so the same evidence bytes
    registered into two different cases can produce the same id in both
    cases' own, separately-stored ``recordings`` tables)."""
    for cid in real_store.iter_case_ids(data_dir):
        conn = appdb.case_db(data_dir, cid).conn
        row = conn.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        if row is not None:
            return _row_to_recording(row)
    return None


def get_recording_in_case(data_dir: str, case_id: str, recording_id: str) -> Recording | None:
    """``recording_id`` looked up *only* within ``case_id``'s own
    ``case.db`` (task FIX-4) — the case-scoped counterpart to
    :func:`get_recording`, for callers (an export, primarily) that already
    know which case they're acting on from their own request path."""
    conn = appdb.case_db(data_dir, case_id).conn
    row = conn.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
    return _row_to_recording(row) if row is not None else None


# --- fingerprint / inferred layout --------------------------------------


def _row_to_vendor_match(row: Any) -> VendorMatch:
    return VendorMatch(
        family=row["family"],
        display_name=row["display_name"],
        platform=row["platform"],
        tier=row["tier"],
        confidence=row["confidence"],
        evidence=json.loads(row["evidence"]),
        model=row["model"],
        serial=row["serial"],
        fs_version=row["fs_version"],
    )


def list_vendor_matches(data_dir: str, evidence_id: str) -> list[VendorMatch]:
    """Ranked ``VendorMatch[]`` for ``evidence_id`` (docs/02-BACKEND.md §4
    ``GET /evidence/{eid}/fingerprint``), from the ``fingerprint`` stage's
    ``vendor_matches`` rows. Empty before the stage has run — matches
    ``pramaan_formats.fingerprint.match``'s own "every family, including
    zero-confidence ones" shape once it has.
    """
    found = real_store.get_evidence_with_case(data_dir, evidence_id)
    if found is None:
        return []
    case_id, _image = found
    conn = appdb.case_db(data_dir, case_id).conn
    rows = conn.execute(
        "SELECT * FROM vendor_matches WHERE image_id = ? ORDER BY confidence DESC, family",
        (evidence_id,),
    ).fetchall()
    return [_row_to_vendor_match(r) for r in rows]


def _row_to_inferred_layout(row: Any) -> InferredLayout:
    return InferredLayout(
        id=row["id"],
        image_id=row["image_id"],
        header_len=row["header_len"],
        magic=row["magic"],
        fields=[InferredField(**f) for f in json.loads(row["fields"])],
        codec=row["codec"],
        confirmed_by=row["confirmed_by"],
    )


def get_inferred_layout(data_dir: str, evidence_id: str) -> InferredLayout | None:
    """The inferred layout for ``evidence_id``, if any — empty until task
    C3 lands ``pramaan_recovery.infer`` (the ``infer_layout`` stage skips
    gracefully until then, so this table is simply empty rather than
    special-cased here).
    """
    found = real_store.get_evidence_with_case(data_dir, evidence_id)
    if found is None:
        return None
    case_id, _image = found
    conn = appdb.case_db(data_dir, case_id).conn
    row = conn.execute(
        "SELECT * FROM inferred_layouts WHERE image_id = ?", (evidence_id,)
    ).fetchone()
    return _row_to_inferred_layout(row) if row is not None else None


def get_inferred_layout_in_case(
    data_dir: str, case_id: str, evidence_id: str
) -> InferredLayout | None:
    """``evidence_id``'s inferred layout looked up *only* within
    ``case_id``'s own ``case.db`` (task FIX-15) — the case-scoped
    counterpart to :func:`get_inferred_layout`, for a caller (a
    ``/cases/{cid}/...`` route) that already knows which case it's
    acting on. Unlike :func:`get_inferred_layout`, this never routes
    through :func:`~pramaan_api.real.store.get_evidence_with_case`'s
    first-sorted-case-wins cross-case scan, so registering identical
    evidence bytes into two different cases (same content-derived
    ``evidence_id``/layout id) correctly returns *this* case's own row,
    including its own independent ``confirmed_by`` state.
    """
    conn = appdb.case_db(data_dir, case_id).conn
    row = conn.execute(
        "SELECT * FROM inferred_layouts WHERE image_id = ?", (evidence_id,)
    ).fetchone()
    return _row_to_inferred_layout(row) if row is not None else None


def get_inferred_layout_by_id(data_dir: str, layout_id: str) -> tuple[str, InferredLayout] | None:
    """``(case_id, InferredLayout)`` for ``layout_id``, scanning every case
    the same way :func:`get_frame_with_case` does — an inferred-layout id
    alone doesn't carry its case (task FIX-1, ``POST
    /inferred-layouts/{lid}/confirm``)."""
    for cid in real_store.iter_case_ids(data_dir):
        conn = appdb.case_db(data_dir, cid).conn
        row = conn.execute("SELECT * FROM inferred_layouts WHERE id = ?", (layout_id,)).fetchone()
        if row is not None:
            return cid, _row_to_inferred_layout(row)
    return None


def set_inferred_layout_confirmed_by(
    data_dir: str, case_id: str, layout_id: str, examiner: str
) -> InferredLayout:
    guarded = appdb.case_db(data_dir, case_id)
    with guarded.lock:
        guarded.conn.execute(
            "UPDATE inferred_layouts SET confirmed_by = ? WHERE id = ?", (examiner, layout_id)
        )
        guarded.conn.commit()
        row = guarded.conn.execute(
            "SELECT * FROM inferred_layouts WHERE id = ?", (layout_id,)
        ).fetchone()
    return _row_to_inferred_layout(row)


def confirm_inferred_layout(data_dir: str, actor: User, layout_id: str) -> InferredLayout | None:
    """Real-mode ``POST /inferred-layouts/{lid}/confirm`` (task FIX-1):
    persists the examiner's confirmation as an audited custody entry, then
    re-indexes the image against the now-confirmed layout so its Tier B
    footage (recordings + frames) becomes listed and playable — the real-
    mode equivalent of the fixture store's ``confirm_inferred_layout``
    (docs/progress/B2.md "Known gaps": "nothing to confirm in real mode
    until C3 populates `inferred_layouts`" — C3 has since landed).

    Role enforcement (only an examiner/admin may confirm — a reviewer may
    not, docs/02-BACKEND.md §11) is the router's job
    (``Depends(require_examiner_or_admin)``), not this function's.

    Idempotent on a *second* confirm of an already-confirmed layout (task
    FIX-4, repro in docs/progress/FIX-2.md "Cross-workstream issues" #2):
    re-running ``_reindex_confirmed_layout`` used to raise
    ``sqlite3.IntegrityError: FOREIGN KEY constraint failed`` (the first
    confirm's ``clips`` stage already inserted ``clips`` rows referencing
    the ``recordings`` this would try to delete and re-insert — see
    ``pramaan_worker.stages.parse_inferred_layout``, now hardened
    separately to delete children first). Belt-and-braces here too: the
    layout and underlying evidence haven't changed between two confirms of
    the *same* layout id, so re-running the whole reindex would only ever
    reproduce byte-identical output (CLAUDE.md rule 5) — a genuine no-op.
    Returns the existing confirmation unchanged and records a distinct,
    honestly-labelled ``layout.confirm_noop`` audit entry (not a second
    ``layout.confirmed``, which would misleadingly imply new confirmation
    work happened) rather than silently doing nothing unaudited.
    """
    found = get_inferred_layout_by_id(data_dir, layout_id)
    if found is None:
        return None
    case_id, layout = found
    return _confirm_layout(data_dir, actor, case_id, layout)


def confirm_inferred_layout_in_case(
    data_dir: str, actor: User, case_id: str, evidence_id: str
) -> InferredLayout | None:
    """Case-scoped counterpart to :func:`confirm_inferred_layout` (task
    FIX-15): resolves the layout via ``(case_id, evidence_id)`` using
    :func:`get_inferred_layout_in_case` instead of
    :func:`get_inferred_layout_by_id`'s cross-case-by-layout-id scan, so
    confirming in a case whose copy of a content-derived ``evidence_id``
    (and therefore the same inferred ``layout.id``) is unconfirmed always
    confirms *that* case's own row — even when another case already
    confirmed its own, independently-stored copy of the identical layout.
    """
    layout = get_inferred_layout_in_case(data_dir, case_id, evidence_id)
    if layout is None:
        return None
    return _confirm_layout(data_dir, actor, case_id, layout)


def _confirm_layout(
    data_dir: str, actor: User, case_id: str, layout: InferredLayout
) -> InferredLayout:
    """Shared confirm body for :func:`confirm_inferred_layout` and
    :func:`confirm_inferred_layout_in_case` (task FIX-15): both resolve
    ``(case_id, layout)`` by different, equally case-scoped means, then
    share this one audited confirm + downstream-reindex implementation."""
    if layout.confirmed_by is not None:
        real_store.append_audit(
            data_dir,
            case_id,
            actor=actor.username,
            role=actor.role,
            action="layout.confirm_noop",
            object_type="inferred_layout",
            object_id=layout.id,
            details={"image_id": layout.image_id, "already_confirmed_by": layout.confirmed_by},
        )
        return layout
    updated = set_inferred_layout_confirmed_by(data_dir, case_id, layout.id, actor.username)
    real_store.append_audit(
        data_dir,
        case_id,
        actor=actor.username,
        role=actor.role,
        action="layout.confirmed",
        object_type="inferred_layout",
        object_id=layout.id,
        details={"image_id": layout.image_id, "header_len": layout.header_len},
    )
    _reindex_confirmed_layout(data_dir, actor, case_id, updated)
    return updated


#: Every stage downstream of parsing that depends on the ``recordings``/
#: frame-index data ``parse_inferred_layout`` just (re)built, in the same
#: order ``JobRunner.run`` would use for the automatic ``/scan`` pipeline
#: (docs/02-BACKEND.md §6, stages 6-11) — including the AI-registered
#: ``timeline``/``motion`` stages (task FIX-12). ``logs`` doesn't itself
#: read ``recordings``/frames (it only reads the raw evidence bytes), but
#: it sits between ``frame_index`` and ``deletion_verdict`` in pipeline
#: order and ``deletion_verdict`` consumes its output
#: (``log_events`` -> actor attribution), so it's re-run here too for a
#: consistent, pipeline-order reindex rather than reaching for its
#: (identical, since it isn't a function of recordings) pre-confirmation
#: result.
_CONFIRM_DOWNSTREAM_STAGES: tuple[str, ...] = (
    "frame_index",
    "logs",
    "deletion_verdict",
    "clips",
    "timeline",
    "motion",
)


def _reindex_confirmed_layout(
    data_dir: str, actor: User, case_id: str, layout: InferredLayout
) -> None:
    """Runs the confirm-triggered equivalent of the automatic ``/scan``
    pipeline's ``parse_index``-equivalent stage plus its downstream stages
    6-11 (docs/02-BACKEND.md §6) for ``layout.image_id`` (task FIX-1
    "Decisions": a real reindex, not a placeholder — see
    ``pramaan_worker.stages.parse_inferred_layout``; task FIX-12: extended
    past ``frame_index``/``clips`` to *every* stage downstream of parsing
    that depends on ``recordings``/frames, in pipeline order — see
    ``_CONFIRM_DOWNSTREAM_STAGES``).

    Before FIX-12, only ``frame_index`` and ``clips`` were re-run here;
    ``deletion_verdict`` (and ``logs``, ``timeline``, ``motion``) kept
    whatever they'd computed during the automatic ``/scan`` — an empty
    ``recordings`` table for any Tier B image at that point, since
    ``recordings`` is only populated once a layout is confirmed. That left
    ``GET /cases/{cid}/deletions`` empty forever after confirming a Tier B
    layout (docs/progress/FIX-11.md "Cross-workstream issues" #1 — the
    precise repro this task fixes).

    Each downstream stage's resumability marker is invalidated first
    (:func:`pramaan_worker.runner.invalidate_stage_markers`) so a later
    ``JobRunner``-driven run of this same evidence (e.g. a ``/scan``
    re-run with unchanged bytes, same ``input_hash``) can't skip a stage
    on the strength of a marker recorded before this reindex — only these
    specific stages' caches are touched, nothing upstream (``hash_verify``,
    ``fingerprint``, ``parse_index``, ``infer_layout``, ``carve``).

    Best-effort: if the image was somehow removed since the layout was
    recorded, or a stage's own dependency genuinely isn't importable, each
    stage function's own degrade-gracefully path (``ok=True,
    skipped=True``) still applies and is still audited — a confirm action
    itself must never fail just because the reindex found nothing to do.
    """
    # Case-scoped (task FIX-4): this function already has `case_id`.
    image = real_store.get_evidence_in_case(data_dir, case_id, layout.image_id)
    if image is None:
        return

    from pramaan_worker.runner import StageContext, invalidate_stage_markers
    from pramaan_worker.stages import clips as clips_stage
    from pramaan_worker.stages import default_stages, parse_inferred_layout
    from pramaan_worker.stages import deletion_verdict as deletion_verdict_stage
    from pramaan_worker.stages import frame_index as frame_index_stage
    from pramaan_worker.stages import logs as logs_stage

    ctx = StageContext(
        case_dir=case_dir(data_dir, case_id),
        image_id=layout.image_id,
        input_hash=f"confirm-{layout.id}",
        evidence_path=image.path,
        expected_sha256=image.sha256,
    )

    invalidate_stage_markers(ctx, _CONFIRM_DOWNSTREAM_STAGES)

    # `timeline`/`motion` are AI-owned (task A2/03-AI-TIMELINE.md); reached
    # only through `pramaan_worker.stages.default_stages()` — the same
    # `register_stage` hook the automatic `/scan` pipeline uses — never by
    # importing an AI package directly here (this task's paths don't
    # include AI routers/`packages/timeline`/`packages/analytics`). Falls
    # back to the harmless placeholder stage if A2's routers haven't been
    # imported yet (e.g. a unit test that builds the FastAPI app without
    # mounting every router).
    ai_stages = default_stages()

    results = [
        ("parse_inferred_layout", parse_inferred_layout(ctx, layout)),
        ("frame_index", frame_index_stage(ctx)),
        ("logs", logs_stage(ctx)),
        ("deletion_verdict", deletion_verdict_stage(ctx)),
        ("clips", clips_stage(ctx)),
        ("timeline", ai_stages["timeline"](ctx)),
        ("motion", ai_stages["motion"](ctx)),
    ]
    for stage_label, result in results:
        real_store.append_audit(
            data_dir,
            case_id,
            actor=actor.username,
            role=actor.role,
            action=f"pipeline.{stage_label}",
            object_type="inferred_layout",
            object_id=layout.id,
            payload_sha256=result.output_hash,
            details={"ok": result.ok, "skipped": result.skipped, "message": result.message},
        )


# --- prove-it hex --------------------------------------------------------


def frame_hex_view(data_dir: str, frame_id: str, before: int, after: int) -> dict[str, Any] | None:
    found = get_frame_with_case(data_dir, frame_id)
    if found is None:
        return None
    case_id, frame = found
    # Case-scoped (task FIX-4): `get_frame_with_case` already resolved
    # which case this frame belongs to.
    image = real_store.get_evidence_in_case(data_dir, case_id, frame.image_id)
    if image is None:
        return None

    reader = EvidenceReader.open(image.path)
    try:
        header_start = (
            frame.header_offset if frame.header_offset is not None else frame.payload_offset
        )
        start = max(0, header_start - before)
        end = min(reader.size, frame.payload_offset + frame.payload_len + after)
        data = reader.read(start, max(end - start, 0))
    finally:
        reader.close()

    header_len = max(frame.payload_offset - start, 0)
    payload_only = data[header_len : header_len + frame.payload_len]
    recomputed = hashlib.sha256(payload_only).hexdigest()
    # FrameRef.payload_sha256 (task FIX-3) is the pure, un-salted sha256 hex
    # of the payload bytes — the genuine "stored" integrity claim to
    # re-prove here. `frame_id` (task FIX-3: `pramaan_core.ids.frame_id`,
    # salted with image_id/offset so two frames sharing identical payload
    # bytes at different offsets don't collide) is no longer a payload hash
    # itself, so it's only a fallback for a `FrameRef` built without
    # `payload_sha256` (an optional field — e.g. a hand-constructed test
    # fixture predating FIX-3, or the stub-mode fixture generator, which
    # has no real bytes to hash).
    if frame.payload_sha256 is not None:
        stored = frame.payload_sha256
        matches = recomputed == stored
    else:
        stored = frame.frame_id
        matches = recomputed.startswith(stored)

    annotations: list[dict[str, Any]] = []
    if header_len > 0:
        annotations.append(
            {"name": "vendor_header", "offset": 0, "length": header_len, "sector": start // 512}
        )
    if header_len >= 4:
        annotations.append(
            {
                "name": "start_code",
                "offset": header_len - 4,
                "length": 4,
                "sector": (start + header_len - 4) // 512,
            }
        )
    annotations.append(
        {
            "name": "payload",
            "offset": header_len,
            "length": len(payload_only),
            "sector": frame.payload_offset // 512,
        }
    )
    return {
        "offset": start,
        "bytes": data,
        "annotations": annotations,
        "payload_sha256_recomputed": recomputed,
        "payload_sha256_stored": stored,
        "matches": matches,
    }


# --- thumbnails (derived, provenance recorded alongside) --------------------


def frame_thumbnail_bytes(data_dir: str, frame_id: str) -> bytes | None:
    found = get_frame_with_case(data_dir, frame_id)
    if found is None:
        return None
    case_id, frame = found
    cdir = case_dir(data_dir, case_id)
    thumbs_dir = cdir / "derived" / "thumbs"
    cache_path = thumbs_dir / f"{frame.frame_id}.jpg"
    if cache_path.exists():
        return cache_path.read_bytes()

    source_frame = frame
    if frame.frame_type != "I":
        rows = _query_frames(
            cdir,
            where="image_id = ? AND channel = ? AND frame_type = 'I' AND payload_offset <= ?",
            params=[frame.image_id, frame.channel, frame.payload_offset],
            limit=1,
        )
        if not rows:
            return None
        source_frame = FrameRef(**rows[0])

    # Case-scoped (task FIX-4): `case_id` was already resolved above.
    image = real_store.get_evidence_in_case(data_dir, case_id, frame.image_id)
    if image is None:
        return None

    thumbs_dir.mkdir(parents=True, exist_ok=True)
    tmp_h264 = thumbs_dir / f"_tmp_{frame.frame_id}.h264"
    reader = EvidenceReader.open(image.path)
    try:
        payload = reader.read(source_frame.payload_offset, source_frame.payload_len)
    finally:
        reader.close()
    # `payload` already spans its own Annex-B start code(s) — a vendor
    # parser/carver's FrameRef.payload_offset points at the access unit's
    # raw elementary-stream bytes (docs/01-FORENSIC-CORE.md §4.6/§4.7).
    tmp_h264.write_bytes(payload)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "h264", "-i", str(tmp_h264), "-frames:v", "1", str(cache_path)],
            check=True,
            capture_output=True,
            timeout=_THUMB_TIMEOUT_S,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        cache_path.unlink(missing_ok=True)
        return None
    finally:
        tmp_h264.unlink(missing_ok=True)

    from pramaan_core.provenance import make_provenance

    prov = make_provenance(
        step="pramaan_api.real.pipeline_store.frame_thumbnail_bytes",
        params={"frame_id": frame.frame_id, "source_frame_id": source_frame.frame_id},
        parent_sha256=image.sha256,
    )
    (thumbs_dir / f"{frame.frame_id}.provenance.json").write_text(
        json.dumps(prov.model_dump(), sort_keys=True), encoding="utf-8"
    )
    return cache_path.read_bytes()


# --- clips (stream-copied derived MP4s) -------------------------------------


def get_clip_path(data_dir: str, clip_id: str) -> Path | None:
    for cid in real_store.iter_case_ids(data_dir):
        conn = appdb.case_db(data_dir, cid).conn
        row = conn.execute("SELECT path FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if row is not None:
            return Path(row["path"])
    return None


# --- logs / deletions --------------------------------------------------


def _row_to_log_event(row: Any) -> LogEvent:
    return LogEvent(
        id=row["id"],
        image_id=row["image_id"],
        ts_device_us=row["ts_device_us"],
        kind=row["kind"],
        user=row["user"],
        channel=row["channel"],
        details=json.loads(row["details"]),
        offset=row["offset"],
    )


def list_log_events(data_dir: str, case_id: str, *, kind: str | None = None) -> list[LogEvent]:
    conn = appdb.case_db(data_dir, case_id).conn
    sql = (
        "SELECT * FROM log_events WHERE image_id IN"
        " (SELECT id FROM evidence_images WHERE case_id = ?)"
    )
    params: list[Any] = [case_id]
    if kind is not None:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY ts_device_us"
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_log_event(r) for r in rows]


def _row_to_deletion_finding(row: Any) -> DeletionFinding:
    return DeletionFinding(
        id=row["id"],
        image_id=row["image_id"],
        channel=row["channel"],
        start_ts_us=row["start_ts_us"],
        end_ts_us=row["end_ts_us"],
        method=row["method"],
        actor=row["actor"],
        action_ts_us=row["action_ts_us"],
        frames_recovered=row["frames_recovered"],
        bytes_recovered=row["bytes_recovered"],
        confidence=row["confidence"],
        reasons=json.loads(row["reasons"]),
        evidence_refs=json.loads(row["evidence_refs"]),
    )


def list_deletions(data_dir: str, case_id: str) -> list[DeletionFinding]:
    conn = appdb.case_db(data_dir, case_id).conn
    rows = conn.execute(
        "SELECT * FROM deletion_findings WHERE image_id IN"
        " (SELECT id FROM evidence_images WHERE case_id = ?) ORDER BY start_ts_us",
        (case_id,),
    ).fetchall()
    return [_row_to_deletion_finding(r) for r in rows]


# --- search --------------------------------------------------------------

_TIMECODE_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})$")


def search(data_dir: str, q: str) -> list[SearchResult]:
    q = q.strip()
    if not q:
        return []
    ql = q.lower()
    results: list[SearchResult] = []
    timecode = _TIMECODE_RE.match(q)
    day_us = (
        (int(timecode.group(1)) * 3600 + int(timecode.group(2)) * 60 + int(timecode.group(3)))
        * 1_000_000
        if timecode
        else None
    )

    for cid in real_store.iter_case_ids(data_dir):
        case = real_store.get_case(data_dir, cid)
        if case is None:
            continue
        if ql in case.case_number.lower() or ql in case.title.lower():
            results.append(
                SearchResult(
                    kind="case",
                    id=case.id,
                    case_id=case.id,
                    label=case.title,
                    detail=case.case_number,
                )
            )
        conn = appdb.case_db(data_dir, cid).conn
        for row in conn.execute(
            "SELECT * FROM evidence_images WHERE case_id = ?", (cid,)
        ).fetchall():
            if ql in row["path"].lower() or ql in row["id"].lower():
                results.append(
                    SearchResult(
                        kind="evidence",
                        id=row["id"],
                        case_id=cid,
                        label=row["path"],
                        detail=f"sha256={row['sha256'][:12]}…",
                    )
                )
        for row in conn.execute(
            "SELECT * FROM recordings WHERE image_id IN"
            " (SELECT id FROM evidence_images WHERE case_id = ?)",
            (cid,),
        ).fetchall():
            if ql in row["id"].lower():
                results.append(
                    SearchResult(
                        kind="recording",
                        id=row["id"],
                        case_id=cid,
                        label=f"channel {row['channel']}",
                        detail=row["source"],
                    )
                )
        for row in conn.execute(
            "SELECT * FROM deletion_findings WHERE image_id IN"
            " (SELECT id FROM evidence_images WHERE case_id = ?)",
            (cid,),
        ).fetchall():
            reasons = json.loads(row["reasons"])
            if ql in row["method"].lower() or any(ql in r.lower() for r in reasons):
                results.append(
                    SearchResult(
                        kind="finding",
                        id=row["id"],
                        case_id=cid,
                        label=row["method"],
                        detail="; ".join(reasons)[:200],
                    )
                )
        if day_us is not None:
            window = 1_000_000  # +/- 1s
            frame_rows = _query_frames(
                case_dir(data_dir, cid),
                where="((ts_header_us % 86400000000) BETWEEN ? AND ?)",
                params=[day_us - window, day_us + window],
                limit=5,
            )
            for fr in frame_rows:
                results.append(
                    SearchResult(
                        kind="frame",
                        id=fr["frame_id"],
                        case_id=cid,
                        label=f"channel {fr['channel']} @ {q}",
                        detail=f"payload_offset={fr['payload_offset']}",
                    )
                )
    return results[:50]
