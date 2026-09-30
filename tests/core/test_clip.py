"""Clip builder tests (docs/01-FORENSIC-CORE.md §4.7 step 6; §5 "Clips:
every clip plays (ffprobe exit 0), zero re-encode (codec parameters
identical to source SPS)"; "Determinism: running the pipeline twice yields
identical ... clip [content hashes]")."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pramaan_core.evidence import EvidenceReader
from pramaan_formats import registry
from pramaan_recovery import vendor_carve
from pramaan_recovery.clip import build_clips, group_runs

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = REPO_ROOT / "corpus" / "images"

FFPROBE = shutil.which("ffprobe")


def _skip_if_missing(image: str) -> None:
    if not (IMAGES_DIR / f"{image}.img").exists():
        pytest.skip(f"corpus/images/{image}.img not generated yet — run `just corpus` first")


def _ffprobe_json(path: Path) -> dict[str, object]:
    assert FFPROBE is not None
    out = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,codec_type,width,height,profile,nb_frames",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        check=True,
    )
    result: dict[str, object] = json.loads(out.stdout)
    return result


@pytest.mark.slow
@pytest.mark.skipif(FFPROBE is None, reason="ffprobe not on PATH")
def test_clip_from_live_hiksim_recording_plays_with_no_reencode(tmp_path: Path) -> None:
    _skip_if_missing("hiksim_clean")
    with EvidenceReader.open(str(IMAGES_DIR / "hiksim_clean.img")) as r:
        parser = registry.get("hiksim")
        rec = next(x for x in parser.list_recordings(r) if x.channel == 1)
        frames = list(parser.iter_frames(r, rec))
        results = build_clips(r, rec.image_id, rec.channel, frames, tmp_path)

    assert len(results) == 1
    clip = results[0]
    assert clip.path.exists()
    assert clip.frame_ids  # non-empty

    probed = _ffprobe_json(clip.path)
    streams = probed["streams"]
    assert isinstance(streams, list) and len(streams) == 1
    stream = streams[0]
    assert stream["codec_name"] == "h264"
    assert stream["codec_type"] == "video"
    assert stream["width"] == 640
    assert stream["height"] == 360
    assert int(stream["nb_frames"]) == len(frames)

    provenance_path = clip.path.with_suffix(clip.path.suffix + ".provenance.json")
    assert provenance_path.exists()
    provenance = json.loads(provenance_path.read_text())
    assert provenance["step"] == "recovery.build_clip"
    assert provenance["tool"] == "pramaan"


@pytest.mark.slow
@pytest.mark.skipif(FFPROBE is None, reason="ffprobe not on PATH")
def test_clip_from_carved_deleted_hiksim_footage_plays(tmp_path: Path) -> None:
    """The whole point of a clip builder for a forensic tool: deleted
    footage recovered by the carver must also be a playable MP4, prepending
    a cached SPS/PPS when a run's leading access unit doesn't carry one."""
    _skip_if_missing("hiksim_format")
    with EvidenceReader.open(str(IMAGES_DIR / "hiksim_format.img")) as r:
        parser = registry.get("hiksim")
        image_id = parser._image_id(r)  # noqa: SLF001
        ranges = parser.unindexed_ranges(r)
        carved = vendor_carve.carve_hiksim_ps(r, image_id, ranges)
        by_channel: dict[int, list] = {}
        for f in carved:
            if f.channel is not None:
                by_channel.setdefault(f.channel, []).append(f)
        assert by_channel  # sanity

        cache: dict[int, bytes] = {}
        any_clip_checked = False
        for channel, frames in by_channel.items():
            out_dir = tmp_path / f"ch{channel}"
            results = build_clips(r, image_id, channel, frames, out_dir, sps_pps_cache=cache)
            for clip in results:
                probed = _ffprobe_json(clip.path)
                streams = probed["streams"]
                assert isinstance(streams, list) and len(streams) == 1
                assert streams[0]["codec_name"] == "h264"
                any_clip_checked = True
        assert any_clip_checked


@pytest.mark.slow
def test_clip_determinism_byte_identical_across_two_runs(tmp_path: Path) -> None:
    _skip_if_missing("hiksim_clean")
    with EvidenceReader.open(str(IMAGES_DIR / "hiksim_clean.img")) as r:
        parser = registry.get("hiksim")
        rec = next(x for x in parser.list_recordings(r) if x.channel == 1)
        frames = list(parser.iter_frames(r, rec))

        results_a = build_clips(r, rec.image_id, rec.channel, frames, tmp_path / "a")
        results_b = build_clips(r, rec.image_id, rec.channel, frames, tmp_path / "b")

    assert len(results_a) == len(results_b) == 1
    hash_a = hashlib.sha256(results_a[0].path.read_bytes()).hexdigest()
    hash_b = hashlib.sha256(results_b[0].path.read_bytes()).hexdigest()
    assert hash_a == hash_b
    assert results_a[0].clip_id == results_b[0].clip_id


def test_group_runs_splits_on_gaps_over_threshold() -> None:
    from pramaan_core.models import FrameRef

    def _frame(offset: int, ts_us: int | None) -> FrameRef:
        return FrameRef(
            frame_id=f"f{offset}",
            image_id="img_test",
            channel=1,
            stream="main",
            codec="h264",
            frame_type="P",
            header_offset=None,
            payload_offset=offset,
            payload_len=10,
            ts_header_us=ts_us,
            ts_index_us=None,
            width=None,
            height=None,
            source="carved",
            recording_id=None,
            deleted=True,
        )

    frames = [
        _frame(0, 0),
        _frame(10, 500_000),
        _frame(20, 1_000_000),
        _frame(30, 5_000_000),  # > 2s gap from the previous frame -> new run
        _frame(40, 5_500_000),
    ]
    runs = group_runs(frames, max_gap_us=2_000_000)
    assert [len(run) for run in runs] == [3, 2]
    assert [f.payload_offset for f in runs[0]] == [0, 10, 20]
    assert [f.payload_offset for f in runs[1]] == [30, 40]


def test_group_runs_never_splits_on_missing_timestamps() -> None:
    from pramaan_core.models import FrameRef

    def _frame(offset: int) -> FrameRef:
        return FrameRef(
            frame_id=f"f{offset}",
            image_id="img_test",
            channel=1,
            stream="main",
            codec="h264",
            frame_type="P",
            header_offset=None,
            payload_offset=offset,
            payload_len=10,
            ts_header_us=None,
            ts_index_us=None,
            width=None,
            height=None,
            source="carved",
            recording_id=None,
            deleted=True,
        )

    frames = [_frame(0), _frame(10), _frame(20)]
    runs = group_runs(frames)
    assert len(runs) == 1
    assert len(runs[0]) == 3
