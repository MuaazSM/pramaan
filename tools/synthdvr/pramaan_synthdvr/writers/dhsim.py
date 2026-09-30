"""DHSIM (Dahua-like, Tier A) writer.

Layout written exactly per docs/01-FORENSIC-CORE.md §4.6 "DHSIM" (superblock,
index, DHAV frames with checksum/footer, DHLG logs). Unlike HIKSIM, DHSIM's
data region is not block-quantized: index entries carry an explicit
(offset, length), so recordings are packed back-to-back with no padding.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pramaan_synthdvr.binutil import fixed_str, put, u16, u32, u64
from pramaan_synthdvr.scenario import (
    TRUE_EPOCH_S,
    default_channels,
    iso,
    seed_for,
    seizure_offset_us,
    us,
)
from pramaan_synthdvr.truth import TruthBuilder, TruthFrame
from pramaan_synthdvr.video import (
    FRAME_INTERVAL_US,
    ChannelSpec,
    ClipSpec,
    MotionEvent,
    au_bytes,
    is_keyframe_au,
    render_elementary_stream,
    split_clip_into_access_units,
)

MAGIC = b"DHFS4.1\x00"
assert len(MAGIC) == 8

SUPERBLOCK_PAGE = 0x1000
INDEX_OFFSET = 0x1000
INDEX_ENTRY_SIZE = 32
RECORDING_FRAMES = 150  # 12 s at 12.5 fps
FORMAT_RECORDING_FRAMES = 60
LOG_RECORD_SIZE = 32
LOG_AREA_CAPACITY = 32

MODEL = "DVR-SIM-DH-8CH"
SERIAL = "SIMDH000123"

DHAV_HEADER_SIZE = 24
DHAV_FOOTER_SIZE = 8
TYPE_I = 0xFD
TYPE_P = 0xFC

KIND_CODE = {
    "power_on": 0x50,
    "login": 0x01,
    "logout": 0x02,
    "playback": 0x10,
    "export": 0x11,
    "hdd_format": 0x40,
    "time_change": 0x41,
}


def _round_up(n: int, unit: int) -> int:
    return ((n + unit - 1) // unit) * unit


def _pack_datetime(dt: datetime) -> int:
    sec = dt.second & 0x3F
    minute = dt.minute & 0x3F
    hour = dt.hour & 0x1F
    day = dt.day & 0x1F
    month = dt.month & 0xF
    year = (dt.year - 2000) & 0x3F
    return sec | (minute << 6) | (hour << 12) | (day << 17) | (month << 22) | (year << 26)


def _dhav_record(payload: bytes, seq: int, channel: int, ts_s: float, is_i: bool) -> bytes:
    total_len = DHAV_HEADER_SIZE + len(payload) + DHAV_FOOTER_SIZE
    dt = datetime.fromtimestamp(ts_s, tz=UTC)
    ms = int(round((ts_s - int(ts_s)) * 1000))
    header = bytearray(DHAV_HEADER_SIZE)
    put(header, 0, b"DHAV")
    header[4] = TYPE_I if is_i else TYPE_P
    header[5] = 0  # subtype
    header[6] = channel & 0xFF
    header[7] = 0  # reserved
    put(header, 8, u32(seq))
    put(header, 12, u32(total_len))
    put(header, 16, u32(_pack_datetime(dt)))
    put(header, 20, u16(ms))
    header[22] = 0  # extension length
    checksum = sum(header[0:23]) & 0xFF
    header[23] = checksum
    footer = b"dhav" + u32(total_len)
    return bytes(header) + payload + footer


@dataclass
class _Recording:
    channel: ChannelSpec
    rec_index: int
    generation: int
    device_start_s: float
    osd_start_s: float
    num_frames: int
    motion: list[MotionEvent]
    id: str = field(default="")
    data_offset: int = 0  # local offset within the data-region buffer
    data_len: int = 0

    def __post_init__(self) -> None:
        self.id = hashlib.sha256(
            f"{self.channel.channel}|{self.generation}|{self.rec_index}".encode()
        ).hexdigest()[:16]

    @property
    def device_end_s(self) -> float:
        return self.device_start_s + self.num_frames * (FRAME_INTERVAL_US / 1_000_000)


def _render_recording(rec: _Recording, name: str, truth: TruthBuilder, data_buf: bytearray) -> None:
    """Render + encode ``rec`` and append its DHAV byte stream to
    ``data_buf`` (offsets recorded are *local* to ``data_buf``; the caller
    adds the final data-region base offset once it's known)."""
    clip = ClipSpec(
        channel=rec.channel,
        num_frames=rec.num_frames,
        start_epoch_s=rec.osd_start_s,
        seed=seed_for(name, str(rec.channel.channel), str(rec.generation), str(rec.rec_index)),
        motion_events=rec.motion,
    )
    stream = render_elementary_stream(clip)
    aus = split_clip_into_access_units(stream)

    rec.data_offset = len(data_buf)
    for i, au in enumerate(aus):
        device_ts_s = rec.device_start_s + i * (FRAME_INTERVAL_US / 1_000_000)
        true_ts_s = device_ts_s  # DHSIM images in this corpus keep device == true
        osd_ts_s = rec.osd_start_s + i * (FRAME_INTERVAL_US / 1_000_000)
        payload = au_bytes(au)
        is_i = is_keyframe_au(au)
        local_offset = len(data_buf)
        record = _dhav_record(payload, i, rec.channel.channel, device_ts_s, is_i)
        data_buf.extend(record)
        payload_local_offset = local_offset + DHAV_HEADER_SIZE
        truth.add_frame(
            TruthFrame(
                channel=rec.channel.channel,
                ts_device_us=us(device_ts_s),
                ts_true_us=us(true_ts_s),
                ts_osd_us=us(osd_ts_s),
                header_offset=payload_local_offset - DHAV_HEADER_SIZE,  # + base, added later
                payload_offset=payload_local_offset,  # + base, added later
                payload_len=len(payload),
                payload_sha256=hashlib.sha256(payload).hexdigest(),
                frame_type="I" if is_i else "P",
                recording_id=rec.id,
                deleted=False,
                overwritten=False,
            )
        )
    rec.data_len = len(data_buf) - rec.data_offset
    if rec.motion:
        truth.motion_events.append(
            {
                "channel": rec.channel.channel,
                "start_true": iso(
                    rec.device_start_s + rec.motion[0].start_frame * (FRAME_INTERVAL_US / 1_000_000)
                ),
                "end_true": iso(
                    rec.device_start_s + rec.motion[0].end_frame * (FRAME_INTERVAL_US / 1_000_000)
                ),
            }
        )


def build_image(
    name: str,
    images_dir: Path,
    truth_dir: Path,
    *,
    scenario: str,
) -> Path:
    """scenario: "format" | "expiry"."""
    channels = default_channels()
    recordings_per_channel = 3 if scenario == "expiry" else 2

    gen1: list[_Recording] = []
    for rec_index in range(recordings_per_channel):
        for ch in channels:
            device_start_s = TRUE_EPOCH_S + rec_index * RECORDING_FRAMES * (
                FRAME_INTERVAL_US / 1_000_000
            )
            motion = [MotionEvent(40, 90)] if (ch.channel == 3 and rec_index == 0) else []
            gen1.append(
                _Recording(
                    channel=ch,
                    rec_index=rec_index,
                    generation=1,
                    device_start_s=device_start_s,
                    osd_start_s=device_start_s,
                    num_frames=RECORDING_FRAMES,
                    motion=motion,
                )
            )

    truth = TruthBuilder(
        image=name,
        family="dhsim",
        tier="A",
        device_model=MODEL,
        device_serial=SERIAL,
        seizure_dvr_displayed="",
        seizure_reference="",
        channels=[{"channel": c.channel, "name": c.name} for c in channels],
        clock_segments=[
            {
                "start_device": iso(gen1[0].device_start_s),
                "end_device": None,
                "offset_true_to_device_us": 0,
            }
        ],
    )

    data_buf = bytearray()
    for rec in gen1:
        _render_recording(rec, name, truth, data_buf)
    gen1_data_len = len(data_buf)

    format_true_s = gen1[-1].device_end_s + 300.0

    gen2: list[_Recording] = []
    gen2_buf = bytearray()
    if scenario == "format":
        for ch in channels:
            device_start_s = format_true_s + 60.0
            gen2.append(
                _Recording(
                    channel=ch,
                    rec_index=0,
                    generation=2,
                    device_start_s=device_start_s,
                    osd_start_s=device_start_s,
                    num_frames=FORMAT_RECORDING_FRAMES,
                    motion=[],
                )
            )
        for rec in gen2:
            _render_recording(rec, name, truth, gen2_buf)
        overwrite_len = len(gen2_buf)
        assert overwrite_len <= gen1_data_len, "gen2 write must fit within gen1's data region"
        data_buf[0:overwrite_len] = gen2_buf
        # gen2 offsets were computed relative to gen2_buf, which starts at
        # the same local position (0) as data_buf, so they're already correct.

    index_capacity = len(gen1)
    index_region_size = _round_up(index_capacity * INDEX_ENTRY_SIZE, 0x1000)
    data_offset = _round_up(INDEX_OFFSET + index_region_size, 0x1000)
    log_area_size = _round_up(LOG_AREA_CAPACITY * LOG_RECORD_SIZE, 0x1000)
    log_offset = data_offset + len(data_buf)
    total_size = log_offset + log_area_size

    img = bytearray(total_size)
    put(img, data_offset, bytes(data_buf))

    # Fix up truth frame offsets now that the absolute data_offset is known.
    for f in truth.frames:
        f.payload_offset += data_offset
        if f.header_offset is not None:
            f.header_offset += data_offset

    # --- index entries ---
    def write_entry(slot: int, rec: _Recording, state: int) -> None:
        off = INDEX_OFFSET + slot * INDEX_ENTRY_SIZE
        e = bytearray(INDEX_ENTRY_SIZE)
        e[0] = state
        e[1] = rec.channel.channel & 0xFF
        put(e, 4, u32(int(rec.device_start_s)))
        put(e, 8, u32(int(rec.device_end_s)))
        put(e, 16, u64(data_offset + rec.data_offset))
        put(e, 24, u64(rec.data_len))
        put(img, off, bytes(e))

    for slot, rec in enumerate(gen1):
        write_entry(slot, rec, state=1)

    log_events: list[dict[str, Any]] = []
    power_on_s = gen1[0].device_start_s - 120.0
    login_s = gen1[0].device_start_s - 60.0
    log_events.append(
        {"ts": int(power_on_s), "kind": "power_on", "user": "system", "channel": 0, "param": 0}
    )
    log_events.append(
        {"ts": int(login_s), "kind": "login", "user": "admin", "channel": 0, "param": 0}
    )

    if scenario == "format":
        for slot, rec in enumerate(gen2):
            write_entry(slot, rec, state=1)  # overwrites the gen1 entry that lived in this slot
        index_entry_count = len(gen2)

        format_login_s = format_true_s - 30.0
        log_events.append(
            {"ts": int(format_login_s), "kind": "login", "user": "admin", "channel": 0, "param": 0}
        )
        log_events.append(
            {
                "ts": int(format_true_s),
                "kind": "hdd_format",
                "user": "admin",
                "channel": 0,
                "param": 0,
            }
        )
        playback_s = gen2[-1].device_end_s + 30.0
        export_s = playback_s + 30.0
        logout_s = export_s + 30.0
        log_events.append(
            {
                "ts": int(playback_s),
                "kind": "playback",
                "user": "admin",
                "channel": gen2[0].channel.channel,
                "param": int(gen2[0].device_start_s),
            }
        )
        log_events.append(
            {
                "ts": int(export_s),
                "kind": "export",
                "user": "admin",
                "channel": gen2[0].channel.channel,
                "param": int(gen2[0].device_start_s),
            }
        )
        log_events.append(
            {"ts": int(logout_s), "kind": "logout", "user": "admin", "channel": 0, "param": 0}
        )
        init_time = int(format_true_s)
    else:
        # expiry: free (state=0) the oldest round's entries; bytes untouched.
        oldest = [r for r in gen1 if r.rec_index == 0]
        for rec in oldest:
            slot = gen1.index(rec)
            write_entry(slot, rec, state=0)
        index_entry_count = len(gen1)

        expiry_action_s = gen1[-1].device_end_s + 10.0
        log_events.append(
            {
                "ts": int(expiry_action_s),
                "kind": "logout",
                "user": "system",
                "channel": 0,
                "param": 0,
            }
        )
        playback_s = gen1[-1].device_end_s + 30.0
        logout_s = playback_s + 30.0
        log_events.append(
            {
                "ts": int(playback_s),
                "kind": "playback",
                "user": "admin",
                "channel": 1,
                "param": int(gen1[-1].device_start_s),
            }
        )
        log_events.append(
            {"ts": int(logout_s), "kind": "logout", "user": "admin", "channel": 0, "param": 0}
        )
        init_time = int(gen1[0].device_start_s - 86_400)

    log_events.sort(key=lambda e: e["ts"])
    assert len(log_events) <= LOG_AREA_CAPACITY
    for i, ev in enumerate(log_events):
        off = log_offset + i * LOG_RECORD_SIZE
        rec_bytes = bytearray(LOG_RECORD_SIZE)
        put(rec_bytes, 0, b"DHLG")
        put(rec_bytes, 4, u32(ev["ts"]))
        put(rec_bytes, 8, u16(KIND_CODE[ev["kind"]]))
        put(rec_bytes, 10, u16(ev["channel"]))
        put(rec_bytes, 12, fixed_str(ev["user"], 16))
        put(rec_bytes, 28, u32(ev["param"]))
        put(img, off, bytes(rec_bytes))
        truth.log_events.append(
            {"kind": ev["kind"], "ts_device": iso(ev["ts"]), "user": ev["user"], "offset": off}
        )

    # --- superblock ---
    put(img, 0x0, MAGIC)
    put(img, 0x10, u64(INDEX_OFFSET))
    put(img, 0x18, u32(index_entry_count))
    put(img, 0x20, u64(data_offset))
    put(img, 0x28, u64(len(data_buf)))
    put(img, 0x30, u32(init_time))
    put(img, 0x40, fixed_str(MODEL, 32))
    put(img, 0x80, fixed_str(SERIAL, 48))
    put(img, 0xC0, u64(log_offset))
    put(img, 0xC8, u64(log_area_size))

    # --- recordings / deletions truth ---
    if scenario == "format":
        per_channel_deleted: dict[int, list[_Recording]] = {}
        for r in gen1:
            per_channel_deleted.setdefault(r.channel.channel, []).append(r)
        for ch_no, recs in per_channel_deleted.items():
            starts = [r.device_start_s for r in recs]
            ends = [r.device_end_s for r in recs]
            truth.deletions.append(
                {
                    "channel": ch_no,
                    "start_device": iso(min(starts)),
                    "end_device": iso(max(ends)),
                    "method": "format",
                    "action_device": iso(format_true_s),
                    "actor": "admin",
                }
            )
        overwrite_end_abs = data_offset + overwrite_len
        for f in truth.frames:
            rec_map = {r.id: r for r in gen1 + gen2}
            rec = rec_map[f.recording_id]
            f.deleted = rec.generation == 1
            if rec.generation == 1:
                f.overwritten = f.payload_offset < overwrite_end_abs
    else:
        for rec in oldest:
            truth.deletions.append(
                {
                    "channel": rec.channel.channel,
                    "start_device": iso(rec.device_start_s),
                    "end_device": iso(rec.device_end_s),
                    "method": "expiry",
                    "action_device": iso(expiry_action_s),
                    "actor": "system",
                }
            )
        oldest_ids = {r.id for r in oldest}
        for f in truth.frames:
            f.deleted = f.recording_id in oldest_ids

    for rec in gen1 + gen2:
        frs = [f for f in truth.frames if f.recording_id == rec.id]
        indexed = True
        if scenario == "format":
            indexed = rec.generation == 2
        elif scenario == "expiry":
            indexed = rec not in oldest
        truth.recordings.append(
            {
                "channel": rec.channel.channel,
                "start_device": iso(rec.device_start_s),
                "end_device": iso(rec.device_end_s),
                "frames": len(frs),
                "byte_ranges": [[data_offset + rec.data_offset, rec.data_len]],
                "indexed": indexed,
                "deleted": frs[0].deleted if frs else False,
                "overwritten_frames": sum(1 for f in frs if f.overwritten),
            }
        )

    seizure_true_s = (gen2[-1].device_end_s if gen2 else gen1[-1].device_end_s) + 3600.0
    ist = timezone(timedelta(hours=5, minutes=30))
    ref_dt = datetime.fromtimestamp(seizure_true_s, tz=ist)
    truth.seizure_reference = ref_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
    disp_dt = ref_dt + timedelta(microseconds=seizure_offset_us(truth.clock_segments))
    truth.seizure_dvr_displayed = disp_dt.strftime("%Y-%m-%dT%H:%M:%S")

    images_dir.mkdir(parents=True, exist_ok=True)
    out_path = images_dir / f"{name}.img"
    out_path.write_bytes(bytes(img))
    truth.write(truth_dir, out_path)
    return out_path
