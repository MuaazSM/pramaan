"""Real (non-fixture) case/evidence/job/custody/anchor store (task B1).

Every *mutating* function here appends a custody entry (docs/02-BACKEND.md
§8: "actions logged: evidence registered/verified, every pipeline stage,
... report generated, export created, anchor created, login/logout") and,
where relevant, publishes a WS event (§7) via ``pramaan_api.real.events``.

Evidence bytes are only ever touched through ``pramaan_core`` (acquire /
EvidenceReader), never opened directly here (CLAUDE.md rule 2).
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pramaan_core.acquire import AcquisitionVerificationError, register_existing
from pramaan_core.ids import content_id
from pramaan_core.models import ClockObservation, EvidenceImage
from pramaan_core.timeutil import utc_now_iso
from pramaan_custody import (
    CustodyEntry,
    FabricAnchor,
    LocalAnchor,
    append_entry,
    load_or_create_keypair,
    public_key_hex,
    read_chain,
)
from pramaan_custody import verify_chain as custody_verify_chain
from pramaan_worker.dramatiq_runner import RedisUnavailable
from pramaan_worker.runner import StageContext, make_runner
from pramaan_worker.stages import default_stages

from pramaan_api.errors import ApiError, bad_request
from pramaan_api.pagination import paginate
from pramaan_api.real import appdb, events
from pramaan_api.real.paths import anchors_ledger_path, case_dir, cases_root, keys_dir
from pramaan_api.schemas import (
    Anchor,
    AuditEntry,
    AuditVerifyResult,
    Case,
    FsEntry,
    Job,
    JobStage,
    SwgdeIntake,
)
from pramaan_api.security import User

_SEEDED_USERNAMES = ("examiner", "reviewer", "admin")


# --- keys / signing ---------------------------------------------------------


def signing_key(data_dir: str, username: str) -> Any:
    return load_or_create_keypair(keys_dir(data_dir), username)


def lab_signing_key(data_dir: str) -> Any:
    return load_or_create_keypair(keys_dir(data_dir), "lab")


def pubkeys(data_dir: str) -> dict[str, str]:
    kdir = keys_dir(data_dir)
    return {name: public_key_hex(load_or_create_keypair(kdir, name)) for name in _SEEDED_USERNAMES}


# --- security: EVIDENCE_ROOTS -----------------------------------------------


def is_within_evidence_roots(evidence_roots: tuple[str, ...], path: str) -> bool:
    """Resolve symlinks and reject traversal (docs/02-BACKEND.md §11)."""
    try:
        resolved = Path(path).resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return False
    for root in evidence_roots:
        try:
            root_resolved = Path(root).resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved == root_resolved or root_resolved in resolved.parents:
            return True
    return False


def fs_browse(evidence_roots: tuple[str, ...], path: str) -> list[FsEntry]:
    if not is_within_evidence_roots(evidence_roots, path):
        return []
    directory = Path(path)
    if not directory.is_dir():
        return []
    entries: list[FsEntry] = []
    for child in sorted(directory.iterdir(), key=lambda p: p.name):
        try:
            stat = child.stat()
        except OSError:
            continue
        modified_dt = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        modified = modified_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
        entries.append(
            FsEntry(
                name=child.name,
                path=str(child),
                is_dir=child.is_dir(),
                size_bytes=None if child.is_dir() else stat.st_size,
                modified_utc=modified,
                looks_like_image=(not child.is_dir())
                and child.suffix.lower() in (".img", ".raw", ".dd", ".e01", ".001", ".bin"),
            )
        )
    return entries


# --- custody -----------------------------------------------------------------


def _to_api_entry(entry: CustodyEntry) -> AuditEntry:
    return AuditEntry(
        seq=entry.seq,
        prev_hash=entry.prev_hash,
        entry_hash=entry.entry_hash,
        ts_utc=entry.ts_utc,
        actor=entry.actor,
        role=entry.role,
        action=entry.action,
        object_type=entry.object_type,
        object_id=entry.object_id,
        payload_sha256=entry.payload_sha256,
        details=entry.details,
        signature=entry.signature,
    )


def append_audit(
    data_dir: str,
    case_id: str,
    *,
    actor: str,
    role: str,
    action: str,
    object_type: str,
    object_id: str,
    payload_sha256: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEntry:
    guarded = appdb.case_db(data_dir, case_id)
    with guarded.lock:
        entry = append_entry(
            guarded.conn,
            case_dir(data_dir, case_id),
            actor=actor,
            role=role,
            action=action,
            object_type=object_type,
            object_id=object_id,
            payload_sha256=payload_sha256,
            details=details or {},
            signing_key=signing_key(data_dir, actor),
        )
    events.publish(
        case_id,
        {
            "type": "audit.appended",
            "seq": entry.seq,
            "entry_hash": entry.entry_hash,
            "action": entry.action,
        },
    )
    return _to_api_entry(entry)


def list_audit(
    data_dir: str, case_id: str, *, cursor: str | None, limit: int | None
) -> tuple[list[AuditEntry], str | None]:
    guarded = appdb.case_db(data_dir, case_id)
    entries = [_to_api_entry(e) for e in read_chain(guarded.conn)]
    return paginate(entries, cursor, limit)


def verify_audit(data_dir: str, case_id: str) -> AuditVerifyResult:
    guarded = appdb.case_db(data_dir, case_id)
    entries = read_chain(guarded.conn)
    result = custody_verify_chain(entries, pubkeys=pubkeys(data_dir))
    return AuditVerifyResult(
        ok=result.ok,
        length=result.length,
        head_hash=result.head_hash,
        first_bad_seq=result.first_bad_seq,
    )


# --- cases -------------------------------------------------------------------


def _row_to_case(row: Any) -> Case:
    return Case(
        id=row["id"],
        case_number=row["case_number"],
        title=row["title"],
        fir_reference=row["fir_number"],
        lab=row["lab"],
        status=row["status"],
        created_utc=row["created_utc"],
        updated_utc=row["updated_utc"],
    )


def create_case(
    data_dir: str,
    actor: User,
    *,
    case_number: str,
    title: str,
    fir_reference: str | None = None,
    lab: str | None = None,
) -> Case:
    guarded = appdb.app_db(data_dir)
    ts = utc_now_iso()
    case_id = content_id(
        "case", {"case_number": case_number, "title": title, "nonce": secrets.token_hex(8)}
    )
    with guarded.lock:
        guarded.conn.execute(
            "INSERT INTO cases "
            "(id, case_number, title, fir_number, lab, status, created_utc, updated_utc) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (case_id, case_number, title, fir_reference, lab, "open", ts, ts),
        )
        guarded.conn.commit()

    # The case's own case.db also has a `cases` table (docs/01-FORENSIC-
    # CORE.md §3.2's schema is applied per case dir) — `evidence_images`'s
    # FOREIGN KEY(case_id) REFERENCES cases(id) is enforced *within that
    # db*, so it needs its own copy of this row too. app.db stays the
    # single source of truth read by get_case/list_cases/patch_case; this
    # mirror is written once, at creation, purely to satisfy the FK.
    case_guarded = appdb.case_db(data_dir, case_id)
    with case_guarded.lock:
        case_guarded.conn.execute(
            "INSERT INTO cases "
            "(id, case_number, title, fir_number, lab, status, created_utc, updated_utc) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (case_id, case_number, title, fir_reference, lab, "open", ts, ts),
        )
        case_guarded.conn.commit()

    case = Case(
        id=case_id,
        case_number=case_number,
        title=title,
        fir_reference=fir_reference,
        lab=lab,
        status="open",
        created_utc=ts,
        updated_utc=ts,
    )
    append_audit(
        data_dir,
        case_id,
        actor=actor.username,
        role=actor.role,
        action="case.created",
        object_type="case",
        object_id=case_id,
        details={"case_number": case_number, "title": title},
    )
    return case


def get_case(data_dir: str, case_id: str) -> Case | None:
    guarded = appdb.app_db(data_dir)
    row = guarded.conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    return _row_to_case(row) if row is not None else None


def list_cases(data_dir: str) -> list[Case]:
    guarded = appdb.app_db(data_dir)
    rows = guarded.conn.execute("SELECT * FROM cases ORDER BY created_utc").fetchall()
    return [_row_to_case(r) for r in rows]


def patch_case(
    data_dir: str,
    actor: User,
    case_id: str,
    *,
    title: str | None,
    fir_reference: str | None,
    lab: str | None,
    status: str | None,
) -> Case | None:
    existing = get_case(data_dir, case_id)
    if existing is None:
        return None
    guarded = appdb.app_db(data_dir)
    ts = utc_now_iso()
    new_title = title if title is not None else existing.title
    new_fir = fir_reference if fir_reference is not None else existing.fir_reference
    new_lab = lab if lab is not None else existing.lab
    new_status = status if status is not None else existing.status
    with guarded.lock:
        guarded.conn.execute(
            "UPDATE cases SET title=?, fir_number=?, lab=?, status=?, updated_utc=? WHERE id=?",
            (new_title, new_fir, new_lab, new_status, ts, case_id),
        )
        guarded.conn.commit()
    updated = Case(
        id=case_id,
        case_number=existing.case_number,
        title=new_title,
        fir_reference=new_fir,
        lab=new_lab,
        status=cast(Any, new_status),
        created_utc=existing.created_utc,
        updated_utc=ts,
    )
    append_audit(
        data_dir,
        case_id,
        actor=actor.username,
        role=actor.role,
        action="case.updated",
        object_type="case",
        object_id=case_id,
        details={"title": new_title, "status": new_status},
    )
    return updated


# --- evidence + ClockObservation ---------------------------------------------


def _row_to_evidence(row: Any) -> EvidenceImage:
    return EvidenceImage(
        id=row["id"],
        path=row["path"],
        format=row["format"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        md5=row["md5"],
        acquired_utc=row["acquired_utc"],
        verified=bool(row["verified"]),
    )


def _parse_wall_clock_us(ts: str) -> int:
    """Microseconds since a *naive* 1970-01-01 epoch, computed purely from
    the calendar value in ``ts`` (any embedded UTC offset is dropped).

    The DVR's displayed time has no reliable timezone of its own (that's
    the whole reason we're recording an offset against a reference clock);
    treating every intake timestamp as a plain wall-clock reading — never
    calling ``.timestamp()``, which would silently pull in the *host
    machine's* local timezone — keeps ``offset_us`` deterministic
    regardless of where this code runs (CLAUDE.md rule 5).
    """
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    epoch = datetime(1970, 1, 1)
    return int((dt - epoch).total_seconds() * 1_000_000)


def _build_clock_observation(image_id: str, intake: SwgdeIntake) -> ClockObservation:
    device_ts_us = _parse_wall_clock_us(intake.dvr_displayed_time)
    reference_ts_us = _parse_wall_clock_us(intake.reference_time)
    offset_us = device_ts_us - reference_ts_us
    details = {
        "reference_source": intake.reference_source,
        "timezone": intake.timezone,
        "seized_at_local": intake.seized_at_local,
        "make_model_label": intake.make_model_label,
        "serial_label": intake.serial_label,
        "write_blocker": intake.write_blocker,
        "notes": intake.notes,
    }
    obs_id = content_id(
        "cko", {"image_id": image_id, "source": "seizure", "intake": intake.model_dump()}
    )
    return ClockObservation(
        id=obs_id,
        image_id=image_id,
        channel=None,
        source="seizure",
        device_ts_us=device_ts_us,
        reference_ts_us=reference_ts_us,
        offset_us=offset_us,
        weight=1.0,
        details=details,
    )


def register_evidence(
    data_dir: str,
    actor: User,
    case_id: str,
    *,
    path: str,
    label: str,
    intake: SwgdeIntake,
) -> EvidenceImage:
    """Hash-and-register an existing file (CLAUDE.md rule 1/2: only
    ``pramaan_core`` opens it, read-only) and record its
    :class:`~pramaan_core.models.ClockObservation` from the SWGDE intake
    (docs/02-BACKEND.md §5).
    """
    try:
        image = register_existing(path)
    except (FileNotFoundError, IsADirectoryError, PermissionError) as exc:
        raise bad_request(f"Could not read evidence at '{path}': {exc}") from exc
    except (
        AcquisitionVerificationError
    ) as exc:  # pragma: no cover - register_existing doesn't verify
        raise bad_request(str(exc)) from exc

    guarded = appdb.case_db(data_dir, case_id)
    clock_obs = _build_clock_observation(image.id, intake)
    with guarded.lock:
        guarded.conn.execute(
            "INSERT OR IGNORE INTO evidence_images "
            "(id, case_id, path, format, size_bytes, sha256, md5, acquired_utc, verified, "
            " provenance) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                image.id,
                case_id,
                image.path,
                image.format,
                image.size_bytes,
                image.sha256,
                image.md5,
                image.acquired_utc,
                int(image.verified),
                None,
            ),
        )
        guarded.conn.execute(
            "INSERT OR IGNORE INTO clock_observations "
            "(id, image_id, channel, source, device_ts_us, reference_ts_us, offset_us, weight, "
            " details) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                clock_obs.id,
                clock_obs.image_id,
                clock_obs.channel,
                clock_obs.source,
                clock_obs.device_ts_us,
                clock_obs.reference_ts_us,
                clock_obs.offset_us,
                clock_obs.weight,
                json.dumps(clock_obs.details, sort_keys=True),
            ),
        )
        guarded.conn.commit()

    append_audit(
        data_dir,
        case_id,
        actor=actor.username,
        role=actor.role,
        action="evidence.registered",
        object_type="evidence",
        object_id=image.id,
        payload_sha256=image.sha256,
        details={
            "path": path,
            "label": label,
            "format": image.format,
            "size_bytes": image.size_bytes,
        },
    )
    return image


def list_evidence(data_dir: str, case_id: str) -> list[EvidenceImage]:
    guarded = appdb.case_db(data_dir, case_id)
    rows = guarded.conn.execute(
        "SELECT * FROM evidence_images WHERE case_id = ?", (case_id,)
    ).fetchall()
    return [_row_to_evidence(r) for r in rows]


def list_clock_observations(data_dir: str, case_id: str, image_id: str) -> list[ClockObservation]:
    guarded = appdb.case_db(data_dir, case_id)
    rows = guarded.conn.execute(
        "SELECT * FROM clock_observations WHERE image_id = ?", (image_id,)
    ).fetchall()
    return [
        ClockObservation(
            id=r["id"],
            image_id=r["image_id"],
            channel=r["channel"],
            source=r["source"],
            device_ts_us=r["device_ts_us"],
            reference_ts_us=r["reference_ts_us"],
            offset_us=r["offset_us"],
            weight=r["weight"],
            details=json.loads(r["details"]),
        )
        for r in rows
    ]


def iter_case_ids(data_dir: str) -> list[str]:
    """Every case id under ``data_dir`` (i.e. every ``cases/<id>/case.db``
    that exists), sorted for deterministic scan order. Used wherever a
    real-mode lookup only has a global id (evidence, frame, clip, ...) and
    must find which case owns it (docs/02-BACKEND.md §4) — fine at this
    demo's scale (a handful of cases per process).
    """
    root = cases_root(data_dir)
    if not root.exists():
        return []
    return sorted(
        candidate.name
        for candidate in root.iterdir()
        if candidate.is_dir() and (candidate / "case.db").exists()
    )


def _find_case_for_evidence(data_dir: str, evidence_id: str) -> str | None:
    for candidate in iter_case_ids(data_dir):
        guarded = appdb.case_db(data_dir, candidate)
        row = guarded.conn.execute(
            "SELECT id FROM evidence_images WHERE id = ?", (evidence_id,)
        ).fetchone()
        if row is not None:
            return candidate
    return None


def get_evidence_with_case(data_dir: str, evidence_id: str) -> tuple[str, EvidenceImage] | None:
    case_id = _find_case_for_evidence(data_dir, evidence_id)
    if case_id is None:
        return None
    guarded = appdb.case_db(data_dir, case_id)
    row = guarded.conn.execute(
        "SELECT * FROM evidence_images WHERE id = ?", (evidence_id,)
    ).fetchone()
    if row is None:
        return None
    return case_id, _row_to_evidence(row)


def get_evidence(data_dir: str, evidence_id: str) -> EvidenceImage | None:
    found = get_evidence_with_case(data_dir, evidence_id)
    return found[1] if found is not None else None


def _mark_evidence_verified(data_dir: str, case_id: str, evidence_id: str) -> None:
    guarded = appdb.case_db(data_dir, case_id)
    with guarded.lock:
        guarded.conn.execute("UPDATE evidence_images SET verified = 1 WHERE id = ?", (evidence_id,))
        guarded.conn.commit()


# --- jobs ----------------------------------------------------------------


_JOBS: dict[str, dict[str, Job]] = {}


def _job_registry(data_dir: str) -> dict[str, Job]:
    return _JOBS.setdefault(data_dir, {})


def get_job(data_dir: str, job_id: str) -> Job | None:
    return _job_registry(data_dir).get(job_id)


def list_jobs(data_dir: str, case_id: str) -> list[Job]:
    return [j for j in _job_registry(data_dir).values() if j.case_id == case_id]


def _job_summary(data_dir: str, case_id: str, image_id: str, stage_count: int) -> dict[str, int]:
    """``job.done`` summary counts (docs/02-BACKEND.md §7:
    ``{recordings, recovered_frames, deletions}``). Falls back to just
    ``stages`` if anything about the summary tables can't be read (e.g. no
    frame index was written at all) — a job that otherwise finished ok must
    never fail just because its summary couldn't be computed.
    """
    try:
        guarded = appdb.case_db(data_dir, case_id)
        recordings = guarded.conn.execute(
            "SELECT COUNT(*) FROM recordings WHERE image_id = ?", (image_id,)
        ).fetchone()[0]
        deletions = guarded.conn.execute(
            "SELECT COUNT(*) FROM deletion_findings WHERE image_id = ?", (image_id,)
        ).fetchone()[0]
        from pramaan_core.frames import query as frames_query

        recovered = frames_query(
            case_dir(data_dir, case_id),
            "SELECT COUNT(*) AS n FROM frames WHERE source = 'carved'",
            image_id=image_id,
        )
        recovered_frames = recovered[0]["n"] if recovered else 0
        return {
            "stages": stage_count,
            "recordings": recordings,
            "recovered_frames": recovered_frames,
            "deletions": deletions,
        }
    except Exception:  # summary is best-effort — never fails an otherwise-ok job
        return {"stages": stage_count}


def run_evidence_job(
    settings_data_dir: str,
    settings_job_backend: str,
    settings_redis_url: str,
    actor: User,
    case_id: str,
    evidence_id: str,
    image: EvidenceImage,
    kind: Literal["scan", "verify"],
    stage_names: list[str],
) -> Job:
    ts = utc_now_iso()
    job_id = content_id(
        "job",
        {
            "case_id": case_id,
            "evidence_id": evidence_id,
            "kind": kind,
            "nonce": secrets.token_hex(8),
        },
    )
    job = Job(
        id=job_id,
        case_id=case_id,
        evidence_id=evidence_id,
        kind=kind,
        status="queued",
        stages=[JobStage(name=n, status="pending", pct=0.0) for n in stage_names],
        pct=0.0,
        created_utc=ts,
        updated_utc=ts,
        log_lines=[],
    )
    _job_registry(settings_data_dir)[job.id] = job
    events.publish(
        case_id,
        {
            "type": "job.progress",
            "job_id": job.id,
            "stage": stage_names[0] if stage_names else "",
            "pct": 0.0,
            "throughput_mbps": 0.0,
            "eta_s": None,
            "message": f"{kind}: queued",
        },
    )
    append_audit(
        settings_data_dir,
        case_id,
        actor=actor.username,
        role=actor.role,
        action=f"job.{kind}.queued",
        object_type="job",
        object_id=job.id,
        details={"evidence_id": evidence_id, "stages": stage_names},
    )

    try:
        runner = make_runner(settings_job_backend, settings_redis_url)
    except RedisUnavailable as exc:
        job.status = "failed"
        job.log_lines.append(str(exc))
        job.updated_utc = utc_now_iso()
        events.publish(
            case_id,
            {
                "type": "job.failed",
                "job_id": job.id,
                "error": {"code": "redis_unavailable", "message": str(exc)},
            },
        )
        return job

    # Verify jobs must always re-hash (never skip via the resumability
    # marker) — a stale "already verified" result would defeat the point
    # of re-verification. A unique input_hash per call guarantees that.
    input_hash = image.sha256 if kind == "scan" else f"verify-{secrets.token_hex(8)}"
    ctx = StageContext(
        case_dir=case_dir(settings_data_dir, case_id),
        image_id=image.id,
        input_hash=input_hash,
        evidence_path=image.path,
        expected_sha256=image.sha256,
    )
    stages_map = default_stages()
    selected = {name: stages_map[name] for name in stage_names if name in stages_map}

    def on_progress(stage: str, pct: float, message: str) -> None:
        events.publish(
            case_id,
            {
                "type": "job.progress",
                "job_id": job.id,
                "stage": stage,
                "pct": pct,
                "throughput_mbps": 0.0,
                "eta_s": 0,
                "message": message,
            },
        )
        events.publish(
            case_id, {"type": "job.log", "job_id": job.id, "level": "info", "line": message}
        )

    job.status = "running"
    results = []
    ok_all = True
    for result in runner.run(
        selected, ctx, stage_order=tuple(stage_names), on_progress=on_progress
    ):
        results.append(result)
        append_audit(
            settings_data_dir,
            case_id,
            actor=actor.username,
            role=actor.role,
            action=f"pipeline.{result.stage}",
            object_type="job",
            object_id=job.id,
            payload_sha256=result.output_hash,
            details={"ok": result.ok, "skipped": result.skipped, "message": result.message},
        )
        if result.stage == "hash_verify":
            events.publish(
                case_id,
                {
                    "type": "evidence.verified",
                    "evidence_id": evidence_id,
                    "sha256": result.output_hash or image.sha256,
                    "match": result.ok,
                },
            )
            if result.ok:
                _mark_evidence_verified(settings_data_dir, case_id, evidence_id)
        if not result.ok:
            ok_all = False
            events.publish(
                case_id,
                {
                    "type": "job.failed",
                    "job_id": job.id,
                    "error": {"code": "stage_failed", "message": result.message},
                },
            )
            break

    stage_by_name = {r.stage: r for r in results}
    job.stages = [
        JobStage(
            name=n,
            status=(
                "done"
                if (n in stage_by_name and stage_by_name[n].ok)
                else ("failed" if n in stage_by_name else "pending")
            ),
            pct=100.0 if (n in stage_by_name and stage_by_name[n].ok) else 0.0,
            message=stage_by_name[n].message if n in stage_by_name else None,
        )
        for n in stage_names
    ]
    job.log_lines = [r.message for r in results]
    job.pct = 100.0 if ok_all else (100.0 * len(results) / max(len(stage_names), 1))
    job.status = "done" if ok_all else "failed"
    job.updated_utc = utc_now_iso()
    if ok_all:
        events.publish(
            case_id,
            {
                "type": "job.done",
                "job_id": job.id,
                "summary": _job_summary(settings_data_dir, case_id, image.id, len(results)),
            },
        )
        append_audit(
            settings_data_dir,
            case_id,
            actor=actor.username,
            role=actor.role,
            action=f"job.{kind}.done",
            object_type="job",
            object_id=job.id,
            details={"stages": len(results)},
        )
    return job


# --- anchors -------------------------------------------------------------


def create_anchor(
    data_dir: str, actor: User, case_id: str, backend: Literal["local", "fabric"]
) -> Anchor:
    guarded = appdb.case_db(data_dir, case_id)
    with guarded.lock:
        entries = read_chain(guarded.conn)
        if not entries:
            raise bad_request("Cannot anchor an empty custody chain — nothing has been logged yet.")
        from_seq, to_seq = entries[0].seq, entries[-1].seq
        hashes_by_seq = {e.seq: e.entry_hash for e in entries}

        if backend == "fabric":
            try:
                record = FabricAnchor().create(case_id, hashes_by_seq, from_seq, to_seq)
            except NotImplementedError as exc:
                raise ApiError(501, "not_implemented", str(exc)) from exc
        else:
            local = LocalAnchor(
                anchors_ledger_path(data_dir), lab_signing_key=lab_signing_key(data_dir)
            )
            record = local.create(case_id, hashes_by_seq, from_seq, to_seq)

        guarded.conn.execute(
            "INSERT INTO anchors "
            "(id, case_id, backend, merkle_root, from_seq, to_seq, ts_utc, lab_signature) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                record.id,
                case_id,
                backend,
                record.merkle_root,
                from_seq,
                to_seq,
                record.ts_utc,
                record.lab_signature,
            ),
        )
        guarded.conn.commit()

    anchor = Anchor(
        id=record.id,
        case_id=case_id,
        merkle_root=record.merkle_root,
        from_seq=from_seq,
        to_seq=to_seq,
        ts_utc=record.ts_utc,
        backend=backend,
        lab_signature=record.lab_signature or "",
    )
    append_audit(
        data_dir,
        case_id,
        actor=actor.username,
        role=actor.role,
        action="anchor.created",
        object_type="anchor",
        object_id=anchor.id,
        details={
            "backend": backend,
            "from_seq": from_seq,
            "to_seq": to_seq,
            "merkle_root": record.merkle_root,
        },
    )
    return anchor


def list_anchors(data_dir: str, case_id: str) -> list[Anchor]:
    guarded = appdb.case_db(data_dir, case_id)
    rows = guarded.conn.execute(
        "SELECT * FROM anchors WHERE case_id = ? ORDER BY ts_utc", (case_id,)
    ).fetchall()
    return [
        Anchor(
            id=r["id"],
            case_id=r["case_id"],
            merkle_root=r["merkle_root"],
            from_seq=r["from_seq"],
            to_seq=r["to_seq"],
            ts_utc=r["ts_utc"],
            backend=r["backend"],
            lab_signature=r["lab_signature"] or "",
        )
        for r in rows
    ]
