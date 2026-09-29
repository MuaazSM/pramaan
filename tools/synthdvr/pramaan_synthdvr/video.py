"""ffmpeg-backed video source with OSD and motion events (docs/05-INFRA-QA.md §4.1).

Frames are rendered pixel-exact in Python (Pillow) rather than via ffmpeg's
`drawtext`/`drawbox` lavfi filters: this machine's ffmpeg 8.1 build has no
libfreetype, so `drawtext` is unavailable (`ffmpeg -filters` does not list
it). Rendering in Python is a strict superset of what the spec's lavfi
recipe would draw (calm background + subtle noise + a moving box during
motion events + burned-in OSD in the vendored OSD font) and is *more*
deterministic, since Pillow's rasterisation doesn't depend on ffmpeg's
libfreetype/fontconfig resolution at all. See docs/progress/Q1.md
"Fallbacks used".

Frames are piped to ffmpeg as raw RGB24 over stdin and encoded to an H.264
baseline Annex B elementary stream with single-thread, fixed, `-bitexact`
flags so the same inputs always produce byte-identical output (verified by
`tests/validation/test_synthdvr_determinism.py`).
"""

from __future__ import annotations

import math
import random
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime

from PIL import Image, ImageDraw, ImageFont

from pramaan_synthdvr.fonts import FONT_PATH, OSD_FONT_SIZE

GOP = 25
FPS = 12.5
FRAME_INTERVAL_US = 80_000  # 80 ms, per docs/05-INFRA-QA.md §4.1

# H.264 NAL unit types we care about.
NAL_SPS = 7
NAL_PPS = 8
NAL_SEI = 6
NAL_IDR = 5
NAL_NON_IDR = 1
VCL_TYPES = (NAL_IDR, NAL_NON_IDR)

_NOISE_TILE_SIZE = 64
_font_cache: dict[int, ImageFont.FreeTypeFont] = {}


def _font(size: int) -> ImageFont.FreeTypeFont:
    f = _font_cache.get(size)
    if f is None:
        f = ImageFont.truetype(str(FONT_PATH), size)
        _font_cache[size] = f
    return f


def _noise_tile(seed: int) -> Image.Image:
    """A small deterministic dither texture, tiled across the frame for
    "subtle noise" without the cost of per-pixel randomness at full frame
    size on every frame."""
    rng = random.Random(seed)
    tile = Image.new("L", (_NOISE_TILE_SIZE, _NOISE_TILE_SIZE))
    px = tile.load()
    assert px is not None
    for y in range(_NOISE_TILE_SIZE):
        for x in range(_NOISE_TILE_SIZE):
            px[x, y] = rng.randint(0, 18)
    return tile.convert("RGB")


@dataclass(frozen=True)
class MotionEvent:
    start_frame: int
    end_frame: int  # exclusive


@dataclass(frozen=True)
class ChannelSpec:
    channel: int
    name: str
    width: int = 640
    height: int = 360


@dataclass(frozen=True)
class ClipSpec:
    """One contiguous elementary stream: one channel, one recording."""

    channel: ChannelSpec
    num_frames: int
    start_epoch_s: float  # OSD/device clock time of frame 0
    seed: int
    motion_events: list[MotionEvent] = field(default_factory=list)


def _render_frame(clip: ClipSpec, i: int, noise: Image.Image) -> bytes:
    w, h = clip.channel.width, clip.channel.height
    img = Image.new("RGB", (w, h), (32, 32, 36))
    for ty in range(0, h, _NOISE_TILE_SIZE):
        for tx in range(0, w, _NOISE_TILE_SIZE):
            box = noise.crop((0, 0, min(_NOISE_TILE_SIZE, w - tx), min(_NOISE_TILE_SIZE, h - ty)))
            img.paste(box, (tx, ty))
    d = ImageDraw.Draw(img)

    in_motion = any(ev.start_frame <= i < ev.end_frame for ev in clip.motion_events)
    if in_motion:
        box_w, box_h = max(24, w // 12), max(24, h // 12)
        cx = int((w / 2) + (w / 3) * math.sin(i * 0.15))
        cy = int((h / 2) + (h / 4) * math.cos(i * 0.11))
        x0 = max(0, min(w - box_w, cx - box_w // 2))
        y0 = max(0, min(h - box_h, cy - box_h // 2))
        d.rectangle([x0, y0, x0 + box_w, y0 + box_h], outline=(220, 40, 40), width=2)

    ts = clip.start_epoch_s + i * (FRAME_INTERVAL_US / 1_000_000)
    stamp = datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    font = _font(OSD_FONT_SIZE)
    d.text((8, 6), f"CH{clip.channel.channel} {clip.channel.name}", font=font, fill=(240, 240, 240))
    tw = d.textlength(stamp, font=font)
    d.text((w - tw - 8, 6), stamp, font=font, fill=(240, 240, 240))

    return img.tobytes()


def render_elementary_stream(clip: ClipSpec) -> bytes:
    """Render ``clip`` and encode it to an H.264 baseline Annex B elementary
    stream, deterministically (single-thread, fixed params, `-bitexact`)."""
    noise = _noise_tile(clip.seed)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-loglevel",
        "error",
        "-threads",
        "1",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{clip.channel.width}x{clip.channel.height}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(GOP),
        "-keyint_min",
        str(GOP),
        "-sc_threshold",
        "0",
        "-x264-params",
        "repeat_headers=1:scenecut=0:rc_lookahead=0:threads=1:sliced_threads=0",
        "-bf",
        "0",
        "-qp",
        "28",
        "-bitexact",
        "-flags:v",
        "+bitexact",
        "-fflags",
        "+bitexact",
        "-f",
        "h264",
        "-",
    ]
    # Render every frame into one buffer first, then hand it to
    # `communicate()` in a single call. `communicate()` (not a manual
    # write-then-read loop) is required here: ffmpeg's stdout pipe fills up
    # well before a multi-second clip's raw RGB input is fully written, and
    # a write-first/read-after loop deadlocks (ffmpeg blocks writing output
    # we haven't started draining, while we're blocked writing input it
    # hasn't gotten to yet). `communicate()` drains stdout on a background
    # thread while stdin is being written, avoiding that deadlock.
    raw = b"".join(_render_frame(clip, i, noise) for i in range(clip.num_frames))
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    out, err = proc.communicate(input=raw)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg encode failed (exit {proc.returncode}): {err.decode(errors='replace')}"
        )
    return out


def find_nals(data: bytes) -> list[tuple[int, bytes]]:
    """Split an Annex B byte string into (nal_type, nal_unit_bytes) pairs.

    ``nal_unit_bytes`` excludes the start code. Handles both 3-byte
    (``00 00 01``) and 4-byte (``00 00 00 01``) start codes.
    """
    i = 0
    n = len(data)
    marks: list[tuple[int, int]] = []
    while i < n - 2:
        if data[i] == 0 and data[i + 1] == 0 and data[i + 2] == 1:
            sc_start = i - 1 if (i > 0 and data[i - 1] == 0) else i
            marks.append((sc_start, i + 3))
            i += 3
        else:
            i += 1
    out: list[tuple[int, bytes]] = []
    for idx, (_sc_start, nal_start) in enumerate(marks):
        nal_end = marks[idx + 1][0] if idx + 1 < len(marks) else n
        nal_type = data[nal_start] & 0x1F
        out.append((nal_type, data[nal_start:nal_end]))
    return out


START_CODE = b"\x00\x00\x00\x01"


def group_access_units(nals: list[tuple[int, bytes]]) -> list[list[tuple[int, bytes]]]:
    """Group NAL units into access units: leading non-VCL NALs (SPS/PPS/SEI/...)
    attach to the following VCL (slice) NAL."""
    aus: list[list[tuple[int, bytes]]] = []
    cur: list[tuple[int, bytes]] = []
    for t, b in nals:
        cur.append((t, b))
        if t in VCL_TYPES:
            aus.append(cur)
            cur = []
    if cur:
        aus.append(cur)
    return aus


def au_bytes(au: list[tuple[int, bytes]]) -> bytes:
    """Canonical Annex B bytes for one access unit: every NAL prefixed with
    a 4-byte start code, concatenated in order."""
    return b"".join(START_CODE + b for _, b in au)


def is_keyframe_au(au: list[tuple[int, bytes]]) -> bool:
    return any(t == NAL_IDR for t, _ in au)


def split_clip_into_access_units(stream: bytes) -> list[list[tuple[int, bytes]]]:
    return group_access_units(find_nals(stream))
