"""HWSIM (Honeywell-like, Tier A) writer.

Layout written exactly per docs/01-FORENSIC-CORE.md §4.6 "HWSIM": a real,
CRC-valid GPT disk (protective MBR, primary + backup GPT header/array),
vendor "machine data" at sector 34, partition 1 (video: header + block-group
index + video block list + video channel list + 20-byte-headered NAL data)
and partition 2 (system: an HWSYS JSON blob).

Sector 34 falls out of the GPT math with no fudging needed: 1 (protective
MBR) + 1 (primary header) + 32 (a standard 128-entry x 128-byte partition
array = 16384 bytes = 32 sectors) = LBA 34 is exactly the first usable LBA.

HWSIM has no documented log format (docs/01-FORENSIC-CORE.md §4.9 only
lists HIKSIM/DHSIM `parse_logs` backends), so there is no log area here and
no log-based actor attribution for its deletion findings — see "actor" in
`build_image`'s `overwrite` branch.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pramaan_synthdvr.binutil import crc32, fixed_str, put, u16, u32, u64
from pramaan_synthdvr.scenario import (
    SEIZURE_DEVICE_OFFSET_S,
    TRUE_EPOCH_S,
    default_channels,
    iso,
    seed_for,
    us,
)
from pramaan_synthdvr.truth import TruthBuilder, TruthFrame
from pramaan_synthdvr.video import (
    FRAME_INTERVAL_US,
    START_CODE,
    VCL_TYPES,
    ChannelSpec,
    ClipSpec,
    MotionEvent,
    is_keyframe_au,
    render_elementary_stream,
    split_clip_into_access_units,
)

SECTOR = 512

# --- GPT constants (UEFI spec field layout) ---
GPT_SIGNATURE = b"EFI PART"
GPT_REVISION = 0x00010000
GPT_HEADER_SIZE = 92
GPT_ENTRY_SIZE = 128
GPT_NUM_ENTRIES = 128
GPT_ARRAY_SECTORS = (GPT_NUM_ENTRIES * GPT_ENTRY_SIZE) // SECTOR  # 32
PRIMARY_HEADER_LBA = 1
PRIMARY_ARRAY_LBA = 2
MACHINE_DATA_LBA = 34  # 2 (MBR + primary header) + 32 (primary array)
PART1_START_LBA = 40  # 5 reserved/unused sectors after the machine-data sector

MODEL = "HWSIM-NVR-8CH"
SERIAL = "SIMHW000123"
MACHINE_DATA_MAGIC = b"HONEYWELL-NVR-SIM\x00"

# --- partition 1 (video) internal layout, per docs/01-FORENSIC-CORE.md §4.6 ---
PART1_BLOCKGROUP_OFF = 0x40
PART1_BLOCKLIST_OFF = 0x40000
PART1_CHANLIST_OFF = 0x400000
PART1_CHANLIST_CAPACITY = 256  # entries; 256 * 16 = 4096 bytes = one 4 KiB page
PART1_DATA_OFF = PART1_CHANLIST_OFF + PART1_CHANLIST_CAPACITY * 16  # 0x401000, 4 KiB-aligned

HW_HDR_SIZE = 20
HW_TYPE_IDR_OR_PARAM = 0x82
HW_TYPE_NON_IDR = 0x02
HW_HDR_FIXED = b"\x80\x01\x00"
NAL_NON_IDR = 1

RECORDING_FRAMES = 75  # 6 s at 12.5 fps
STREAM_MAIN = 0x00


def _round_up(n: int, unit: int) -> int:
    return ((n + unit - 1) // unit) * unit


def _guid(name: str, tag: str) -> bytes:
    """Deterministic 16-byte GUID (no wall-clock/random UUIDs allowed in a
    hashed artefact — CLAUDE.md rule 5)."""
    return hashlib.sha256(f"{name}|{tag}".encode()).digest()[:16]


def _protective_mbr(total_sectors: int) -> bytes:
    mbr = bytearray(SECTOR)
    entry = bytearray(16)
    entry[0] = 0x00  # not bootable
    entry[1:4] = bytes([0x00, 0x02, 0x00])  # CHS start (dummy, disk is LBA-addressed)
    entry[4] = 0xEE  # GPT protective partition type
    entry[5:8] = bytes([0xFF, 0xFF, 0xFF])  # CHS end (dummy)
    put(entry, 8, u32(1))
    put(entry, 12, u32(min(total_sectors - 1, 0xFFFFFFFF)))
    put(mbr, 0x1BE, bytes(entry))
    put(mbr, 0x1FE, bytes([0x55, 0xAA]))
    return bytes(mbr)


def _gpt_header(
    *,
    my_lba: int,
    alt_lba: int,
    first_usable: int,
    last_usable: int,
    disk_guid: bytes,
    part_entry_lba: int,
    part_array_crc: int,
) -> bytes:
    h = bytearray(SECTOR)
    put(h, 0, GPT_SIGNATURE)
    put(h, 8, u32(GPT_REVISION))
    put(h, 12, u32(GPT_HEADER_SIZE))
    put(h, 16, u32(0))  # header_crc32 placeholder, filled below
    put(h, 20, u32(0))  # reserved
    put(h, 24, u64(my_lba))
    put(h, 32, u64(alt_lba))
    put(h, 40, u64(first_usable))
    put(h, 48, u64(last_usable))
    put(h, 56, disk_guid)
    put(h, 72, u64(part_entry_lba))
    put(h, 80, u32(GPT_NUM_ENTRIES))
    put(h, 84, u32(GPT_ENTRY_SIZE))
    put(h, 88, u32(part_array_crc))
    crc = crc32(bytes(h[0:GPT_HEADER_SIZE]))  # computed with header_crc32 itself zeroed
    put(h, 16, u32(crc))
    return bytes(h)


def _gpt_entry(
    *, type_guid: bytes, unique_guid: bytes, start_lba: int, end_lba: int, name: str
) -> bytes:
    e = bytearray(GPT_ENTRY_SIZE)
    put(e, 0, type_guid)
    put(e, 16, unique_guid)
    put(e, 32, u64(start_lba))
    put(e, 40, u64(end_lba))
    put(e, 48, u64(0))  # attributes
    put(e, 56, name.encode("utf-16-le")[:72])
    return bytes(e)


def _partition_array(entries: list[bytes]) -> bytes:
    arr = bytearray(GPT_NUM_ENTRIES * GPT_ENTRY_SIZE)
    for i, e in enumerate(entries):
        put(arr, i * GPT_ENTRY_SIZE, e)
    return bytes(arr)


def _blockgroup_entry(group_start_ts: int, group_number: int) -> bytes:
    e = bytearray(16)
    put(e, 4, u32(group_start_ts))
    put(e, 8, u32(group_number))
    return bytes(e)


def _block_list_entry(block_start_ts: int, block_number: int, group_number: int) -> bytes:
    # 16-byte entry: u32 reserved(0) · u32 block_start_ts · 3 pad · u8
    # block_number · u8 group_number · 3 pad (the spec's "7 pad" doesn't sum
    # to a 16-byte stride with the other named fields at their literal
    # offsets — same class of off-by-a-few-pad-bytes issue Q1 documented
    # for HIKSIM's HIKBTREE/RATS records; only the trailing pad is resized
    # here, every named field keeps its literal offset).
    e = bytearray(16)
    put(e, 4, u32(block_start_ts))
    e[11] = block_number & 0xFF
    e[12] = group_number & 0xFF
    return bytes(e)


def _channel_list_entry(
    *, channel: int, stream: int, start_ts: int, start_offset_4k: int, length_4k: int
) -> bytes:
    e = bytearray(16)
    e[0] = channel & 0xFF
    e[1] = stream & 0xFF
    put(e, 4, u32(start_ts))
    put(e, 8, u32(start_offset_4k))
    put(e, 12, u32(length_4k))
    return bytes(e)


def _hw_frame_header(
    is_idr_or_param: bool, width: int, height: int, nal_len: int, ts_us: int
) -> bytes:
    h = bytearray(HW_HDR_SIZE)
    h[0] = HW_TYPE_IDR_OR_PARAM if is_idr_or_param else HW_TYPE_NON_IDR
    put(h, 1, HW_HDR_FIXED)
    put(h, 4, u16(width))
    put(h, 6, u16(height))
    put(h, 8, u32(nal_len))
    put(h, 12, u64(ts_us))
    return bytes(h)


@dataclass
class _Recording:
    channel: ChannelSpec
    round_index: int
    device_start_s: float
    num_frames: int
    motion: list[MotionEvent] = field(default_factory=list)
    id: str = field(default="")
    data_offset: int = 0  # local offset within the video-data buffer being built
    data_len: int = 0

    def __post_init__(self) -> None:
        self.id = hashlib.sha256(f"{self.channel.channel}|{self.round_index}".encode()).hexdigest()[
            :16
        ]

    @property
    def device_end_s(self) -> float:
        return self.device_start_s + self.num_frames * (FRAME_INTERVAL_US / 1_000_000)


def _write_run(rec: _Recording, name: str, truth: TruthBuilder, run_buf: bytearray) -> None:
    """Render + encode ``rec``'s clip and append its HWSIM per-NAL byte
    stream to ``run_buf`` (offsets recorded are local to ``run_buf``; the
    caller adds the data-region base offset once it's known).

    Every NAL of every access unit gets its own 20-byte header
    (docs/01-FORENSIC-CORE.md §4.6: "Video data: per NAL, a 20-byte custom
    header") — SPS/PPS/IDR NALs are typed 0x82 ("IDR/parameter set"),
    non-IDR slice NALs 0x02. One ground-truth `TruthFrame` is recorded per
    *access unit* (matching every other writer's per-frame truth
    granularity), pointing at that access unit's own slice NAL's
    header/payload specifically; a HWSIM-aware carver reassembles the
    leading SPS/PPS NALs by walking backward from a slice NAL header,
    exactly as the generic carver's AU-grouping step already does for any
    format (docs/01-FORENSIC-CORE.md §4.7).
    """
    clip = ClipSpec(
        channel=rec.channel,
        num_frames=rec.num_frames,
        start_epoch_s=rec.device_start_s,
        seed=seed_for(name, str(rec.channel.channel), str(rec.round_index)),
        motion_events=rec.motion,
    )
    stream = render_elementary_stream(clip)
    aus = split_clip_into_access_units(stream)

    rec.data_offset = len(run_buf)
    for i, au in enumerate(aus):
        device_ts_s = rec.device_start_s + i * (FRAME_INTERVAL_US / 1_000_000)
        ts_us = us(device_ts_s)
        slice_offset: int | None = None
        slice_bytes: bytes | None = None
        for t, nal in au:
            nal_bytes = START_CODE + nal
            is_idr_or_param = t != NAL_NON_IDR
            header = _hw_frame_header(
                is_idr_or_param, rec.channel.width, rec.channel.height, len(nal_bytes), ts_us
            )
            offset = len(run_buf)
            run_buf.extend(header)
            run_buf.extend(nal_bytes)
            if t in VCL_TYPES:
                slice_offset = offset
                slice_bytes = nal_bytes
        assert slice_offset is not None and slice_bytes is not None
        is_i = is_keyframe_au(au)
        truth.add_frame(
            TruthFrame(
                channel=rec.channel.channel,
                ts_device_us=ts_us,
                ts_true_us=ts_us,
                ts_osd_us=ts_us,
                header_offset=slice_offset,
                payload_offset=slice_offset + HW_HDR_SIZE,
                payload_len=len(slice_bytes),
                payload_sha256=hashlib.sha256(slice_bytes).hexdigest(),
                frame_type="I" if is_i else "P",
                recording_id=rec.id,
                deleted=False,
                overwritten=False,
            )
        )
    # End-of-run sentinel (20 zero bytes), then 0xEE pad to the next 4 KiB
    # boundary (docs/01-FORENSIC-CORE.md §4.6). Runs are packed back-to-back
    # from a 4 KiB-aligned base (`PART1_DATA_OFF`), so a local 4 KiB
    # boundary is also an absolute one.
    run_buf.extend(bytes(HW_HDR_SIZE))
    pad = (-len(run_buf)) % 4096
    run_buf.extend(b"\xee" * pad)
    rec.data_len = len(run_buf) - rec.data_offset
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


def build_image(name: str, images_dir: Path, truth_dir: Path, *, scenario: str) -> Path:
    """scenario: "format" | "overwrite"."""
    channels = default_channels()

    def make_round(round_index: int, start_s: float, num_frames: int) -> list[_Recording]:
        return [
            _Recording(
                channel=ch,
                round_index=round_index,
                device_start_s=start_s,
                num_frames=num_frames,
                motion=[MotionEvent(20, 45)] if (ch.channel == 3 and round_index == 0) else [],
            )
            for ch in channels
        ]

    truth = TruthBuilder(
        image=name,
        family="hwsim",
        tier="A",
        device_model=MODEL,
        device_serial=SERIAL,
        seizure_dvr_displayed="",
        seizure_reference="",
        channels=[{"channel": c.channel, "name": c.name} for c in channels],
        clock_segments=[
            {"start_device": iso(TRUE_EPOCH_S), "end_device": None, "offset_true_to_device_us": 0}
        ],
    )

    round_gap_s = RECORDING_FRAMES * (FRAME_INTERVAL_US / 1_000_000) + 60.0

    if scenario == "format":
        round0 = make_round(0, TRUE_EPOCH_S, RECORDING_FRAMES)
        round1 = make_round(1, TRUE_EPOCH_S + round_gap_s, RECORDING_FRAMES)
        gen1 = round0 + round1
        format_true_s = round1[0].device_end_s + 300.0
        # header reset -> round index counts from 0 again
        gen2 = make_round(0, format_true_s + 60.0, RECORDING_FRAMES)

        data_buf = bytearray()
        for rec in gen1:
            _write_run(rec, name, truth, data_buf)
        gen1_len = len(data_buf)

        gen2_buf = bytearray()
        for rec in gen2:
            _write_run(rec, name, truth, gen2_buf)
        overwrite_len = len(gen2_buf)
        assert overwrite_len <= gen1_len, "gen2 write must fit within gen1's data region"
        data_buf[0:overwrite_len] = gen2_buf

        live_recs = gen2
        all_recs = gen1 + gen2
        for f in truth.frames:
            rec = next(r for r in all_recs if r.id == f.recording_id)
            f.deleted = rec in gen1
            if rec in gen1:
                f.overwritten = f.payload_offset < overwrite_len

        total_allocatable = gen1_len
        available_bytes = total_allocatable - len(gen2_buf)
        next_write_offset_local = len(gen2_buf)
        groups = [(int(gen2[0].device_start_s), 0)]
        blocks = [(rec.device_start_s, i, 0) for i, rec in enumerate(gen2)]

        deletions_source = gen1
        deletion_method = "format"
        action_true_s = format_true_s
        actor: str | None = "admin"

    elif scenario == "overwrite":
        rounds: list[list[_Recording]] = []
        t = TRUE_EPOCH_S
        for round_i in range(4):
            rounds.append(make_round(round_i, t, RECORDING_FRAMES))
            t += round_gap_s
        round0, round1, round2, round3 = rounds

        data_buf = bytearray()
        for rec in round0 + round1 + round2:
            _write_run(rec, name, truth, data_buf)

        round3_buf = bytearray()
        for rec in round3:
            _write_run(rec, name, truth, round3_buf)
        overwrite_len = len(round3_buf)
        # round3 is written with the same channel count/frame count as
        # round0, so it is exactly the same physical size and fully
        # occupies round0's old (oldest, circular-buffer-wrapped) slot,
        # leaving round1/round2 completely untouched -- this is the
        # generator-side model of docs/05-INFRA-QA.md §4.2's "overwrite":
        # "disk filled, oldest blocks overwritten by new footage".
        assert overwrite_len <= len(data_buf)
        data_buf[0:overwrite_len] = round3_buf

        live_recs = round1 + round2 + round3
        all_recs = round0 + round1 + round2 + round3
        for f in truth.frames:
            rec = next(r for r in all_recs if r.id == f.recording_id)
            f.deleted = rec in round0
            if rec in round0:
                f.overwritten = f.payload_offset < overwrite_len

        total_allocatable = len(data_buf)
        available_bytes = 0
        next_write_offset_local = overwrite_len
        groups = [
            (int(round1[0].device_start_s), 1),
            (int(round2[0].device_start_s), 2),
            (int(round3[0].device_start_s), 3),
        ]
        blocks = [(rec.device_start_s, i, rec.round_index) for i, rec in enumerate(live_recs)]

        deletions_source = round0
        deletion_method = "overwrite"
        action_true_s = round3[0].device_start_s
        # HWSIM has no log area at all (docs/01-FORENSIC-CORE.md §4.9 only
        # lists HIKSIM/DHSIM `parse_logs` backends), so there is no
        # log-based evidence to attribute an actor for this finding.
        actor = None
    else:
        raise ValueError(f"unknown hwsim scenario {scenario!r}")

    # ---- assemble partition 1 ----
    channel_list_entries = []
    for rec in live_recs:
        channel_list_entries.append(
            _channel_list_entry(
                channel=rec.channel.channel,
                stream=STREAM_MAIN,
                start_ts=int(rec.device_start_s),
                start_offset_4k=rec.data_offset // 4096,
                length_4k=rec.data_len // 4096,
            )
        )
    assert len(channel_list_entries) <= PART1_CHANLIST_CAPACITY

    part1 = bytearray(PART1_DATA_OFF + len(data_buf))
    put(part1, 0x00, u64(PART1_DATA_OFF))
    put(part1, 0x08, u64(PART1_DATA_OFF + next_write_offset_local))
    put(part1, 0x10, u64(available_bytes))
    put(part1, 0x18, u64(total_allocatable))

    bg_off = PART1_BLOCKGROUP_OFF
    for group_ts, gnum in groups:
        put(part1, bg_off, _blockgroup_entry(group_ts, gnum))
        bg_off += 16
    put(part1, bg_off, bytes(16))  # all-zero terminator entry

    bl_off = PART1_BLOCKLIST_OFF
    for block_ts, block_number, group_number in blocks:
        put(part1, bl_off, _block_list_entry(int(block_ts), block_number, group_number))
        bl_off += 16
    put(part1, bl_off, bytes(16))

    cl_off = PART1_CHANLIST_OFF
    for e in channel_list_entries:
        put(part1, cl_off, e)
        cl_off += 16
    put(part1, cl_off, bytes(16))

    put(part1, PART1_DATA_OFF, bytes(data_buf))

    # ---- partition 2 (HWSYS system blob) ----
    hwsys = {"format": "HWSYS", "model": MODEL, "serial": SERIAL, "timezone": "Asia/Kolkata"}
    part2_payload = (json.dumps(hwsys, sort_keys=True) + "\n").encode("utf-8")
    part2 = bytearray(_round_up(len(part2_payload), SECTOR))
    put(part2, 0, part2_payload)

    # ---- GPT geometry ----
    part1_start_lba = PART1_START_LBA
    part1_sectors = _round_up(len(part1), SECTOR) // SECTOR
    part2_start_lba = part1_start_lba + part1_sectors
    part2_sectors = _round_up(len(part2), SECTOR) // SECTOR
    last_usable_lba = part2_start_lba + part2_sectors - 1
    backup_array_lba = last_usable_lba + 1
    backup_header_lba = backup_array_lba + GPT_ARRAY_SECTORS
    total_sectors = backup_header_lba + 1
    first_usable_lba = MACHINE_DATA_LBA

    entries = [
        _gpt_entry(
            type_guid=_guid(name, "type-video"),
            unique_guid=_guid(name, "uniq-video"),
            start_lba=part1_start_lba,
            end_lba=part2_start_lba - 1,
            name="HWSIM-VIDEO",
        ),
        _gpt_entry(
            type_guid=_guid(name, "type-sys"),
            unique_guid=_guid(name, "uniq-sys"),
            start_lba=part2_start_lba,
            end_lba=last_usable_lba,
            name="HWSIM-SYS",
        ),
    ]
    array_bytes = _partition_array(entries)
    array_crc = crc32(array_bytes)
    disk_guid = _guid(name, "disk-guid")

    primary_header = _gpt_header(
        my_lba=PRIMARY_HEADER_LBA,
        alt_lba=backup_header_lba,
        first_usable=first_usable_lba,
        last_usable=last_usable_lba,
        disk_guid=disk_guid,
        part_entry_lba=PRIMARY_ARRAY_LBA,
        part_array_crc=array_crc,
    )
    backup_header = _gpt_header(
        my_lba=backup_header_lba,
        alt_lba=PRIMARY_HEADER_LBA,
        first_usable=first_usable_lba,
        last_usable=last_usable_lba,
        disk_guid=disk_guid,
        part_entry_lba=backup_array_lba,
        part_array_crc=array_crc,
    )

    machine_data = bytearray(SECTOR)
    put(machine_data, 0, MACHINE_DATA_MAGIC)
    put(machine_data, len(MACHINE_DATA_MAGIC), fixed_str(MODEL, 32))
    put(machine_data, len(MACHINE_DATA_MAGIC) + 32, fixed_str(SERIAL, 32))

    img = bytearray(total_sectors * SECTOR)
    put(img, 0, _protective_mbr(total_sectors))
    put(img, PRIMARY_HEADER_LBA * SECTOR, primary_header)
    put(img, PRIMARY_ARRAY_LBA * SECTOR, array_bytes)
    put(img, MACHINE_DATA_LBA * SECTOR, bytes(machine_data))
    put(img, part1_start_lba * SECTOR, bytes(part1))
    put(img, part2_start_lba * SECTOR, bytes(part2))
    put(img, backup_array_lba * SECTOR, array_bytes)
    put(img, backup_header_lba * SECTOR, backup_header)

    # ---- fix up truth frame offsets now that absolute addressing is known ----
    part1_base = part1_start_lba * SECTOR
    data_base = part1_base + PART1_DATA_OFF
    for f in truth.frames:
        f.payload_offset += data_base
        if f.header_offset is not None:
            f.header_offset += data_base

    for rec in all_recs:
        frs = [f for f in truth.frames if f.recording_id == rec.id]
        truth.recordings.append(
            {
                "channel": rec.channel.channel,
                "start_device": iso(rec.device_start_s),
                "end_device": iso(rec.device_end_s),
                "frames": len(frs),
                "byte_ranges": [[data_base + rec.data_offset, rec.data_len]],
                "indexed": rec in live_recs,
                "deleted": frs[0].deleted if frs else False,
                "overwritten_frames": sum(1 for f in frs if f.overwritten),
            }
        )

    per_channel_deleted: dict[int, list[_Recording]] = {}
    for r in deletions_source:
        per_channel_deleted.setdefault(r.channel.channel, []).append(r)
    for ch_no, recs in per_channel_deleted.items():
        starts = [r.device_start_s for r in recs]
        ends = [r.device_end_s for r in recs]
        truth.deletions.append(
            {
                "channel": ch_no,
                "start_device": iso(min(starts)),
                "end_device": iso(max(ends)),
                "method": deletion_method,
                "action_device": iso(action_true_s),
                "actor": actor,
            }
        )

    seizure_true_s = live_recs[-1].device_end_s + 3600.0
    ist = timezone(timedelta(hours=5, minutes=30))
    ref_dt = datetime.fromtimestamp(seizure_true_s, tz=ist)
    truth.seizure_reference = ref_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
    disp_dt = ref_dt + timedelta(seconds=SEIZURE_DEVICE_OFFSET_S)
    truth.seizure_dvr_displayed = disp_dt.strftime("%Y-%m-%dT%H:%M:%S")

    images_dir.mkdir(parents=True, exist_ok=True)
    out_path = images_dir / f"{name}.img"
    out_path.write_bytes(bytes(img))
    truth.write(truth_dir, out_path)
    return out_path
