"""Real (non-fixture) signed MP4 export (task B3, docs/02-BACKEND.md §10)."""

from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path
from typing import Any

from pramaan_core.evidence import EvidenceReader
from pramaan_core.models import FrameRef
from pramaan_core.timeutil import utc_now_iso
from pramaan_export import (
    ExportMuxError,
    ExportResult,
    NoFramesToExport,
    VerifyOutcome,
    build_export,
)
from pramaan_export import verify_export_bytes as _verify_export_bytes

from pramaan_api.errors import bad_request, not_found, unprocessable
from pramaan_api.real import appdb
from pramaan_api.real import pipeline_store as pstore
from pramaan_api.real import store as real_store
from pramaan_api.real.paths import case_dir
from pramaan_api.schemas import ExportRecord
from pramaan_api.security import User
from pramaan_api.settings import Settings

#: Frame count large enough to never truncate a real export within this
#: environment's corpus (list_frames' own API default of 500 is a UI page
#: size, not an export-correctness limit).
_EXPORT_FRAME_LIMIT = 2_000_000


def _tool_version() -> str:
    try:
        return metadata.version("pramaan-core")
    except metadata.PackageNotFoundError:
        return "0.0.0+unknown"


def _exports_dir(data_dir: str, case_id: str) -> Path:
    return case_dir(data_dir, case_id) / "exports"


def _select_frames(
    data_dir: str,
    case_id: str,
    *,
    recording_id: str | None,
    channel: int | None,
    from_norm_us: int | None,
    to_norm_us: int | None,
) -> tuple[list[FrameRef], str, int | None]:
    """Returns ``(frames, image_id, resolved_channel)``.

    ``from_norm_us``/``to_norm_us`` filter on the frame's own device-clock
    header timestamp (``ts_header_us``) — the AI timeline workstream (A2)
    is what produces a true *normalised* clock (``ts_norm_us``); until a
    frame carries that field, this is documented as a known approximation
    (see docs/progress/B3.md "Known gaps").
    """
    if recording_id is not None:
        # Case-scoped (task FIX-4): `recording_id` is a stable hash of
        # (image_id, channel, start, offset), so the same evidence bytes
        # registered into a *different* case can produce the same id
        # there too. `_select_frames` already has the case_id this export
        # request is actually for (`/cases/{cid}/exports`) -- use it,
        # rather than `get_recording`'s cross-case scan silently resolving
        # to whichever other case happens to sort first.
        recording = pstore.get_recording_in_case(data_dir, case_id, recording_id)
        if recording is None:
            raise not_found("recording", recording_id)
        frames = pstore.list_frames(
            data_dir, case_id, recording_id=recording_id, limit=_EXPORT_FRAME_LIMIT
        )
        return frames, recording.image_id, recording.channel

    if channel is None:
        raise bad_request("Provide either recording_id, or channel (with an optional time range).")
    frames = pstore.list_frames(
        data_dir,
        case_id,
        channel=channel,
        frm=from_norm_us,
        to=to_norm_us,
        limit=_EXPORT_FRAME_LIMIT,
    )
    if not frames:
        raise bad_request("No frames match the requested channel/time range.")
    return frames, frames[0].image_id, channel


def create_export(
    settings: Settings,
    actor: User,
    case_id: str,
    *,
    recording_id: str | None,
    channel: int | None,
    from_norm_us: int | None,
    to_norm_us: int | None,
) -> ExportRecord:
    data_dir = settings.data_dir
    if real_store.get_case(data_dir, case_id) is None:
        raise not_found("case", case_id)

    frames, image_id, resolved_channel = _select_frames(
        data_dir,
        case_id,
        recording_id=recording_id,
        channel=channel,
        from_norm_us=from_norm_us,
        to_norm_us=to_norm_us,
    )
    # Case-scoped for the same reason as `get_recording_in_case` above —
    # `create_export` already has this request's `case_id`.
    image = real_store.get_evidence_in_case(data_dir, case_id, image_id)
    if image is None:
        raise not_found("evidence", image_id)

    signing_key = real_store.signing_key(data_dir, actor.username)
    out_dir = _exports_dir(data_dir, case_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    reader = EvidenceReader.open(image.path)
    try:
        try:
            result: ExportResult = build_export(
                reader,
                source_image_id=image_id,
                source_sha256=image.sha256,
                channel=resolved_channel,
                recording_id=recording_id,
                frames=frames,
                from_norm_us=from_norm_us,
                to_norm_us=to_norm_us,
                examiner_username=actor.username,
                examiner_role=actor.role,
                signing_key=signing_key,
                out_dir=out_dir,
                tool_version=_tool_version(),
            )
        except NoFramesToExport as exc:
            raise bad_request(str(exc)) from exc
        except ExportMuxError as exc:
            # Task FIX-4: this used to propagate as an uncaught 500 (real
            # repro: a live HWSIM recording whose carved frame stream
            # starts mid-GOP with no SPS/PPS — ffmpeg's stream-copy remux
            # can't handle that; the underlying missing-SPS/PPS gap is
            # CORE FIX-5's, not this one's, to fix). The request itself
            # was well-formed and the evidence is genuinely readable — the
            # server just can't produce a *valid* signed export from these
            # particular frames yet, which is a 422, not a 500 or a 400.
            raise unprocessable(
                "This recording could not be exported: its video stream could not be"
                " remuxed without re-encoding (CLAUDE.md rule 3 forbids re-encoding"
                f" original video). {exc}",
                code="export_not_playable",
                details={
                    "image_id": image_id,
                    "recording_id": recording_id,
                    "channel": resolved_channel,
                },
            ) from exc
    finally:
        reader.close()

    created_utc = utc_now_iso()

    guarded = appdb.case_db(data_dir, case_id)
    with guarded.lock:
        guarded.conn.execute(
            "INSERT OR REPLACE INTO exports "
            "(id, case_id, recording_id, path, manifest_sha256, signature_path, created_utc, "
            " created_by) VALUES (?,?,?,?,?,?,?,?)",
            (
                result.export_id,
                case_id,
                recording_id,
                str(result.mp4_path),
                result.manifest_sha256,
                str(result.signature_path),
                created_utc,
                actor.username,
            ),
        )
        guarded.conn.commit()

    real_store.append_audit(
        data_dir,
        case_id,
        actor=actor.username,
        role=actor.role,
        action="export.created",
        object_type="export",
        object_id=result.export_id,
        payload_sha256=result.manifest_sha256,
        details={
            "recording_id": recording_id,
            "channel": resolved_channel,
            "frame_count": len(frames),
        },
    )

    return _to_export_record(result, case_id, created_utc, actor.username)


def _to_export_record(
    result: ExportResult, case_id: str, created_utc: str, examiner: str
) -> ExportRecord:
    manifest = result.manifest
    time_range = manifest.get("normalised_time_range_us", {})
    return ExportRecord(
        id=result.export_id,
        case_id=case_id,
        recording_id=manifest.get("recording_id"),
        channel=manifest.get("channel"),
        from_norm_us=time_range.get("from"),
        to_norm_us=time_range.get("to"),
        created_utc=created_utc,
        examiner=examiner,
        file_path=str(result.mp4_path),
        signature_path=str(result.signature_path),
        manifest_sha256=result.manifest_sha256,
    )


def _row_to_export_record(data_dir: str, row: Any) -> ExportRecord:
    mp4_path = Path(row["path"])
    manifest: dict[str, Any] = {}
    manifest_path = mp4_path.with_suffix(".manifest.json")
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            manifest = {}
    time_range = manifest.get("normalised_time_range_us", {})
    return ExportRecord(
        id=row["id"],
        case_id=row["case_id"],
        recording_id=row["recording_id"],
        channel=manifest.get("channel"),
        from_norm_us=time_range.get("from"),
        to_norm_us=time_range.get("to"),
        created_utc=row["created_utc"],
        examiner=row["created_by"] or "",
        file_path=row["path"],
        signature_path=row["signature_path"],
        manifest_sha256=row["manifest_sha256"],
    )


def list_exports(data_dir: str, case_id: str) -> list[ExportRecord]:
    guarded = appdb.case_db(data_dir, case_id)
    rows = guarded.conn.execute(
        "SELECT * FROM exports WHERE case_id = ? ORDER BY created_utc", (case_id,)
    ).fetchall()
    return [_row_to_export_record(data_dir, r) for r in rows]


def get_export(data_dir: str, export_id: str) -> ExportRecord | None:
    for cid in real_store.iter_case_ids(data_dir):
        guarded = appdb.case_db(data_dir, cid)
        row = guarded.conn.execute("SELECT * FROM exports WHERE id = ?", (export_id,)).fetchone()
        if row is not None:
            return _row_to_export_record(data_dir, row)
    return None


def get_export_file_path(data_dir: str, export_id: str) -> Path | None:
    for cid in real_store.iter_case_ids(data_dir):
        guarded = appdb.case_db(data_dir, cid)
        row = guarded.conn.execute(
            "SELECT path FROM exports WHERE id = ?", (export_id,)
        ).fetchone()
        if row is not None:
            return Path(row["path"])
    return None


def verify_export(data_dir: str, file_bytes: bytes) -> tuple[VerifyOutcome, bool]:
    """Verify an uploaded export's signature/integrity, and separately
    whether its claimed source hash matches a registered evidence image in
    *any* case (docs §10: "whether the source hashes match a registered
    evidence image")."""
    pubkeys = real_store.pubkeys(data_dir)
    outcome = _verify_export_bytes(file_bytes, pubkey_hex_by_username=pubkeys)
    source_sha256 = outcome.manifest.get("source_sha256")
    matches = False
    if source_sha256:
        for cid in real_store.iter_case_ids(data_dir):
            for image in real_store.list_evidence(data_dir, cid):
                if image.sha256 == source_sha256:
                    matches = True
                    break
            if matches:
                break
    return outcome, matches
