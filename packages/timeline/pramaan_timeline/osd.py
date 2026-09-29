"""Robust on-screen-display (OSD) time reader with an engine fallback chain
(docs/03-AI-TIMELINE.md §4 step 4): PaddleOCR -> RapidOCR -> Tesseract ->
pure numpy/PIL glyph template matcher.

Disk/dependency policy (docs/progress/A1.md "Fallbacks used", CLAUDE.md —
this dev machine has ~13 GiB free): PaddleOCR and RapidOCR are declared only
under optional extras in ``packages/timeline/pyproject.toml`` that
``just setup`` does not install, and are imported lazily here — on this
machine both report themselves unavailable with a clear reason via
``OcrEngine.available()``. Tesseract runs through ``pytesseract`` against
the system ``tesseract`` binary (5.5.1, installed system-wide). The template
matcher is pure numpy/PIL, requires no optional dependency, and is always
available — it is the guaranteed last resort every test can rely on.
"""

from __future__ import annotations

import importlib.util
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pramaan_timeline.clock import robust_median_offset
from pramaan_timeline.patterns import parse_datetime_text

#: (left, top, right, bottom) in pixels, PIL's ``Image.crop`` convention.
BBox = tuple[int, int, int, int]

#: Bundled with the package (docs/05-INFRA-QA.md §4.1: the synthetic
#: generator renders OSD text in "Geist Mono or DejaVu Sans Mono"). Copied
#: from a local TeX Live install (Bitstream Vera-derived licence, freely
#: redistributable — see docs/progress/A1.md "Decisions"). Overridable via
#: ``TemplateEngine(font_path=...)`` if Q1's generator settles on Geist Mono
#: instead; see docs/progress/A1.md for the reconciliation note.
ASSET_FONT_PATH = Path(__file__).resolve().parent / "assets" / "DejaVuSansMono.ttf"


@dataclass(frozen=True, slots=True)
class OcrReading:
    """One successful OSD read."""

    text: str
    device_ts_us: int
    pattern: str
    confidence: float
    bbox: BBox
    engine: str


class OcrEngine(Protocol):
    name: str

    def available(self) -> tuple[bool, str]:
        """Whether this engine can run here, and why (or why not)."""
        ...

    def locate(self, image: Image.Image) -> OcrReading | None:
        """Search the whole frame for OSD date-time text."""
        ...

    def read_crop(self, image: Image.Image, bbox: BBox) -> OcrReading | None:
        """Read OSD date-time text from a previously discovered crop."""
        ...


def _offset_bbox(local: BBox, base: BBox | None) -> BBox:
    if base is None:
        return local
    left, top, right, bottom = local
    base_left, base_top, _, _ = base
    return (left + base_left, top + base_top, right + base_left, bottom + base_top)


# --------------------------------------------------------------------------
# PaddleOCR (optional extra "paddle"; not installed by `just setup`)
# --------------------------------------------------------------------------


class PaddleEngine:
    name = "paddleocr"

    def __init__(self) -> None:
        self._ocr: Any | None = None

    def available(self) -> tuple[bool, str]:
        if importlib.util.find_spec("paddleocr") is None:
            return False, (
                "paddleocr not installed — declared only under the optional "
                "'paddle' extra (packages/timeline/pyproject.toml), which "
                "`just setup` deliberately does not install on this "
                "disk-constrained machine (docs/progress/A1.md 'Fallbacks used')"
            )
        return True, "paddleocr importable"

    def locate(self, image: Image.Image) -> OcrReading | None:
        return self._run(image, None)

    def read_crop(self, image: Image.Image, bbox: BBox) -> OcrReading | None:
        return self._run(image, bbox)

    def _engine(self) -> Any:
        if self._ocr is None:
            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(lang="en", show_log=False)
        return self._ocr

    def _run(self, image: Image.Image, bbox: BBox | None) -> OcrReading | None:
        target = image if bbox is None else image.crop(bbox)
        result = self._engine().ocr(np.asarray(target.convert("RGB")), cls=False)
        for line in result or []:
            for box, (text, score) in line:
                parsed = parse_datetime_text(text)
                if parsed is None:
                    continue
                xs = [point[0] for point in box]
                ys = [point[1] for point in box]
                local_bbox = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
                return OcrReading(
                    text=text,
                    device_ts_us=parsed.device_ts_us,
                    pattern=parsed.pattern,
                    confidence=float(score),
                    bbox=_offset_bbox(local_bbox, bbox),
                    engine=self.name,
                )
        return None


# --------------------------------------------------------------------------
# RapidOCR (optional extra "rapidocr"; not installed by `just setup`)
# --------------------------------------------------------------------------


class RapidEngine:
    name = "rapidocr"

    def __init__(self) -> None:
        self._ocr: Any | None = None

    def available(self) -> tuple[bool, str]:
        if importlib.util.find_spec("rapidocr_onnxruntime") is None:
            return False, (
                "rapidocr_onnxruntime not installed — declared only under "
                "the optional 'rapidocr' extra (packages/timeline/pyproject.toml); "
                "not installed by `just setup` (docs/progress/A1.md 'Fallbacks used')"
            )
        return True, "rapidocr_onnxruntime importable"

    def locate(self, image: Image.Image) -> OcrReading | None:
        return self._run(image, None)

    def read_crop(self, image: Image.Image, bbox: BBox) -> OcrReading | None:
        return self._run(image, bbox)

    def _engine(self) -> Any:
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
        return self._ocr

    def _run(self, image: Image.Image, bbox: BBox | None) -> OcrReading | None:
        target = image if bbox is None else image.crop(bbox)
        result, _elapse = self._engine()(np.asarray(target.convert("RGB")))
        for box, text, score in result or []:
            parsed = parse_datetime_text(text)
            if parsed is None:
                continue
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            local_bbox = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
            return OcrReading(
                text=text,
                device_ts_us=parsed.device_ts_us,
                pattern=parsed.pattern,
                confidence=float(score),
                bbox=_offset_bbox(local_bbox, bbox),
                engine=self.name,
            )
        return None


# --------------------------------------------------------------------------
# Tesseract (system binary, via pytesseract)
# --------------------------------------------------------------------------


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _decode_tesseract_data(data: dict[str, list[Any]], base_bbox: BBox | None) -> OcrReading | None:
    count = len(data.get("text", []))
    lines: dict[tuple[int, int, int], list[int]] = {}
    for i in range(count):
        text = str(data["text"][i]).strip()
        if not text:
            continue
        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        lines.setdefault(key, []).append(i)

    for indices in lines.values():
        line_text = " ".join(str(data["text"][i]) for i in indices).strip()
        parsed = parse_datetime_text(line_text)
        if parsed is None:
            continue
        lefts = [int(data["left"][i]) for i in indices]
        tops = [int(data["top"][i]) for i in indices]
        rights = [int(data["left"][i]) + int(data["width"][i]) for i in indices]
        bottoms = [int(data["top"][i]) + int(data["height"][i]) for i in indices]
        local_bbox = (min(lefts), min(tops), max(rights), max(bottoms))

        raw_confs = (_safe_int(data["conf"][i]) for i in indices)
        confs = [c for c in raw_confs if c is not None and c >= 0]
        confidence = (sum(confs) / len(confs) / 100.0) if confs else 0.5

        return OcrReading(
            text=line_text,
            device_ts_us=parsed.device_ts_us,
            pattern=parsed.pattern,
            confidence=confidence,
            bbox=_offset_bbox(local_bbox, base_bbox),
            engine="tesseract",
        )
    return None


class TesseractEngine:
    name = "tesseract"

    def available(self) -> tuple[bool, str]:
        if importlib.util.find_spec("pytesseract") is None:
            return False, "pytesseract not installed"
        if shutil.which("tesseract") is None:
            return False, "tesseract binary not found on PATH"
        return True, "pytesseract + system tesseract binary available"

    def locate(self, image: Image.Image) -> OcrReading | None:
        import pytesseract

        data: dict[str, list[Any]] = pytesseract.image_to_data(
            image, output_type=pytesseract.Output.DICT
        )
        return _decode_tesseract_data(data, base_bbox=None)

    def read_crop(self, image: Image.Image, bbox: BBox) -> OcrReading | None:
        import pytesseract

        # Tesseract's layout analysis is unreliable on a crop with zero
        # margin around the ink (common OCR practice: pad the ROI a
        # little); pad and clamp to the source image bounds, then translate
        # results back into the caller's original bbox coordinate frame.
        pad = 6
        padded = (
            max(bbox[0] - pad, 0),
            max(bbox[1] - pad, 0),
            min(bbox[2] + pad, image.width),
            min(bbox[3] + pad, image.height),
        )
        crop = image.crop(padded)
        data: dict[str, list[Any]] = pytesseract.image_to_data(
            crop, output_type=pytesseract.Output.DICT
        )
        return _decode_tesseract_data(data, base_bbox=padded)


# --------------------------------------------------------------------------
# Template matcher: pure numpy/PIL glyph matching, always available
# --------------------------------------------------------------------------

#: Charset the synthetic OSD ever renders (docs/05-INFRA-QA.md §4.1:
#: ``%Y-%m-%d %H:%M:%S``, fixed-width digits plus '-', ':' and a space).
_TEMPLATE_CHARSET = "0123456789-: "

#: Fixed character length of that format, e.g. "2026-03-12 16:45:12".
_FIXED_FORMAT_LEN = len("2026-03-12 16:45:12")


@dataclass
class _TemplateGlyphs:
    cell_w: int
    cell_h: int
    templates: dict[str, np.ndarray]
    #: Binarised (foreground/background) version of each template, used for
    #: IoU matching (see ``_match_glyph``) — much more discriminative
    #: between visually similar digits (e.g. '0' vs '3') than a raw
    #: grayscale correlation once antialiasing/resize noise is involved.
    binary_templates: dict[str, np.ndarray]


#: Non-blank characters of ``_TEMPLATE_CHARSET``, in a fixed reference order.
_REFERENCE_STRING = "0123456789-:"


def _build_template_glyphs(font_path: Path, font_size: int) -> _TemplateGlyphs:
    """Render the reference digits/punctuation once as *one* string and
    slice per-character cells out of it, rather than rendering each glyph
    on its own canvas.

    This matters: ``font.getbbox(text)`` (used by ``_decode_fixed_cells``
    below to tightly crop a candidate OSD region) returns the *ink* extent
    of the whole string, which for digits sits near the bottom of the
    font's full ascent/descent box — a lone glyph rendered into its own
    canvas at a fixed offset would carry several rows of blank ascender
    space that the tightly-cropped real string never has, misaligning
    every template vertically against real crops and making every match
    score near-random. Slicing cells from one tightly-cropped reference
    render keeps the templates in the exact same vertical frame as
    whatever ``_decode_fixed_cells`` will crop out of a real frame.
    """
    font = ImageFont.truetype(str(font_path), font_size)
    ref_bbox = font.getbbox(_REFERENCE_STRING)
    height = int(round(ref_bbox[3] - ref_bbox[1]))
    advance = font.getlength("0")
    cell_w = int(round(advance))

    canvas_w = int(round(font.getlength(_REFERENCE_STRING))) + 2
    canvas = Image.new("L", (max(canvas_w, 1), max(height, 1)), color=0)
    draw = ImageDraw.Draw(canvas)
    draw.text((-ref_bbox[0], -ref_bbox[1]), _REFERENCE_STRING, font=font, fill=255)
    arr = np.asarray(canvas, dtype=np.float64)

    templates: dict[str, np.ndarray] = {" ": np.zeros((max(height, 1), cell_w), dtype=np.float64)}
    for i, ch in enumerate(_REFERENCE_STRING):
        x0 = int(round(i * advance))
        x1 = x0 + cell_w
        templates[ch] = arr[:, x0:x1]
    binary_templates = {ch: _binarize(tmpl) for ch, tmpl in templates.items()}
    return _TemplateGlyphs(
        cell_w=cell_w, cell_h=max(height, 1), templates=templates, binary_templates=binary_templates
    )


def _resize_to(arr: np.ndarray, width: int, height: int) -> np.ndarray:
    width = max(width, 1)
    height = max(height, 1)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    resized = img.resize((width, height), Image.Resampling.BILINEAR)
    return np.asarray(resized, dtype=np.float64)


def _binarize(arr: np.ndarray) -> np.ndarray:
    """Foreground/background mask: pixels brighter than the cell's own
    midpoint. Threshold is per-cell (not a global constant) so this works
    regardless of the image's absolute brightness/contrast.
    """
    lo, hi = float(arr.min()), float(arr.max())
    if hi - lo < 1e-6:
        return np.zeros(arr.shape, dtype=bool)
    return arr > (lo + (hi - lo) * 0.5)


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    intersection = int(np.logical_and(a, b).sum())
    union = int(np.logical_or(a, b).sum())
    if union == 0:
        return 1.0 if intersection == 0 else 0.0
    return intersection / union


def _match_glyph(cell: np.ndarray, glyphs: _TemplateGlyphs) -> tuple[str, float]:
    resized = _resize_to(cell, glyphs.cell_w, glyphs.cell_h)
    cell_mask = _binarize(resized)
    cell_mask_inv = ~cell_mask
    best_char = " "
    best_score = -1.0
    for ch, mask in glyphs.binary_templates.items():
        # max(): a crop may be light-text-on-dark or dark-text-on-light;
        # try both polarities and keep whichever the template agrees with.
        score = max(_iou(cell_mask, mask), _iou(cell_mask_inv, mask))
        if score > best_score:
            best_score = score
            best_char = ch
    return best_char, max(best_score, 0.0)


def _decode_at(
    gray: np.ndarray, glyphs: _TemplateGlyphs, cell_w: float, x_offset: float
) -> tuple[str, float]:
    height, width = gray.shape
    chars: list[str] = []
    scores: list[float] = []
    for i in range(_FIXED_FORMAT_LEN):
        x0 = int(round(x_offset + i * cell_w))
        x1 = max(int(round(x_offset + (i + 1) * cell_w)), x0 + 1)
        x0 = min(max(x0, 0), width)
        x1 = min(max(x1, x0 + 1), width)
        if x0 >= width:
            return "", 0.0
        cell = gray[:, x0:x1]
        ch, score = _match_glyph(cell, glyphs)
        chars.append(ch)
        scores.append(score)
    return "".join(chars), (sum(scores) / len(scores) if scores else 0.0)


def _decode_fixed_cells(crop: Image.Image, glyphs: _TemplateGlyphs) -> tuple[str, float]:
    """Decode a crop as ``_FIXED_FORMAT_LEN`` fixed-width character cells.

    Tries both a cell width derived from the crop itself (assumes the crop
    spans exactly the fixed-length string, no padding) and the glyph set's
    own native cell width (assumes the crop was rendered at the same font
    size as the template glyphs, per ``TemplateEngine(font_size=...)``),
    each at several horizontal starting offsets — a discovered bbox's left
    edge is an ink threshold, not necessarily the exact glyph origin, and a
    one- or two-pixel misalignment cascades into every following cell.
    Keeps whichever (scale, offset) combination scores highest.
    """
    gray = np.asarray(crop.convert("L"), dtype=np.float64)
    height, width = gray.shape
    if width == 0 or height == 0:
        return "", 0.0

    best_text = ""
    best_score = -1.0
    for cell_w in {width / _FIXED_FORMAT_LEN, float(glyphs.cell_w)}:
        span = cell_w * _FIXED_FORMAT_LEN
        max_offset = max(0.0, width - span)
        steps = min(max(int(round(max_offset)) + 1, 1), 9)
        offsets = np.linspace(0.0, max_offset, num=steps) if max_offset > 0 else [0.0]
        for x_offset in offsets:
            text, score = _decode_at(gray, glyphs, cell_w, float(x_offset))
            if text and score > best_score:
                best_text, best_score = text, score

    return best_text, max(best_score, 0.0)


def _contiguous_ranges(mask: np.ndarray, max_gap: int) -> list[tuple[int, int]]:
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    ranges: list[tuple[int, int]] = []
    start = int(idx[0])
    prev = int(idx[0])
    for value in idx[1:]:
        v = int(value)
        if v - prev > max_gap + 1:
            ranges.append((start, prev))
            start = v
        prev = v
    ranges.append((start, prev))
    return ranges


def find_text_blobs(
    gray: np.ndarray, *, min_area_frac: float = 0.0008, col_gap: int | None = None
) -> list[BBox]:
    """Locate candidate text blobs in a grayscale frame via intensity
    projection — pure numpy, no OpenCV (CLAUDE.md / A1's dependency
    constraints). Returns bounding boxes widest-first: in the synthetic
    corpus the date-time string is wider than the ``CHn <name>`` label
    (docs/05-INFRA-QA.md §4.1), so trying the widest blob first finds the
    OSD clock before anything else.

    ``col_gap`` (pixels) controls how big a blank run within a text row
    may be before it's treated as a boundary between two separate blobs
    (e.g. the label vs. the date-time) rather than in-word spacing (e.g.
    the space between the date and the time, or letter spacing); if
    ``None``, a fraction of the image width is used. Callers unsure of the
    right value should prefer :func:`iter_candidate_bboxes`, which tries a
    range of thresholds.
    """
    if gray.size == 0:
        return []
    arr = gray.astype(np.float64)
    background = float(np.median(arr))
    spread = float(arr.max() - arr.min())
    if spread < 8.0:
        return []
    # A low threshold (relative to the frame's own contrast) keeps
    # antialiased glyph edges in the mask, so the detected bbox tracks the
    # font's own tight ink extent (``font.getbbox``) closely — a coarser
    # threshold clips a couple of edge pixels per character, which then
    # misaligns every fixed-width cell downstream (see A1's decode notes).
    ink = np.abs(arr - background) > (spread * 0.08)

    height, width = arr.shape
    row_mask = ink.mean(axis=1) > 0.02
    min_area = min_area_frac * height * width
    gap = col_gap if col_gap is not None else max(4, width // 40)

    # A couple of pixels of padding around each blob: the ink mask still
    # clips the very faintest antialiased fringe, and a fixed-width cell
    # decode is sensitive to the outermost characters being a pixel or two
    # narrower than the ones in the middle. Padding into uniform background
    # is harmless (it matches the blank margin the template glyphs already
    # carry); padding into real content would not be, which is why this
    # stays small.
    pad = 3
    blobs: list[BBox] = []
    for r0, r1 in _contiguous_ranges(row_mask, max_gap=1):
        band = ink[r0 : r1 + 1, :]
        col_mask = band.mean(axis=0) > 0.0
        for c0, c1 in _contiguous_ranges(col_mask, max_gap=gap):
            area = (r1 - r0 + 1) * (c1 - c0 + 1)
            if area < min_area:
                continue
            blobs.append(
                (max(c0 - pad, 0), r0, min(c1 + 1 + pad, width), r1 + 1)
            )

    blobs.sort(key=lambda b: (b[2] - b[0]), reverse=True)
    return blobs


#: Column-gap thresholds :func:`iter_candidate_bboxes` tries, smallest
#: first: small values separate adjacent words (a label from a date-time
#: string sharing a row); large values re-merge a string's own internal
#: word-spacing (e.g. the space between the date and time) that a small
#: threshold would otherwise wrongly split into two blobs.
_BLOB_GAP_CANDIDATES: tuple[int, ...] = (4, 8, 16, 32, 64, 128, 256)


def iter_candidate_bboxes(gray: np.ndarray) -> list[BBox]:
    """:func:`find_text_blobs` at several column-gap thresholds, deduped,
    smallest-gap-first (finer separation before coarser merging)."""
    seen: set[BBox] = set()
    candidates: list[BBox] = []
    for gap in _BLOB_GAP_CANDIDATES:
        for bbox in find_text_blobs(gray, col_gap=gap):
            if bbox in seen:
                continue
            seen.add(bbox)
            candidates.append(bbox)
    return candidates


class TemplateEngine:
    """Pure numpy/PIL glyph template matcher — the guaranteed fallback.

    Assumes the fixed synthetic OSD format ``%Y-%m-%d %H:%M:%S`` (docs/05-
    INFRA-QA.md §4.1): a monospace string of exactly ``_FIXED_FORMAT_LEN``
    characters drawn from ``_TEMPLATE_CHARSET``. General free-form OSD text
    (weekday prefixes, 12h clocks, slash-separated dates) is out of scope
    for this engine by design — those are handled by the OCR engines above
    when available; the template matcher exists specifically because the
    synthetic corpus's font and format are known in advance.
    """

    name = "template"

    def __init__(self, font_path: str | Path | None = None, font_size: int = 28) -> None:
        self._font_path = Path(font_path) if font_path is not None else ASSET_FONT_PATH
        self._font_size = font_size
        self._glyphs: _TemplateGlyphs | None = None

    def available(self) -> tuple[bool, str]:
        if not self._font_path.is_file():
            return False, f"template glyph font not found at {self._font_path}"
        return True, "pure numpy/PIL glyph template matcher (guaranteed fallback)"

    def _glyph_set(self) -> _TemplateGlyphs:
        if self._glyphs is None:
            self._glyphs = _build_template_glyphs(self._font_path, self._font_size)
        return self._glyphs

    def read_crop(self, image: Image.Image, bbox: BBox) -> OcrReading | None:
        crop = image.crop(bbox)
        text, confidence = _decode_fixed_cells(crop, self._glyph_set())
        parsed = parse_datetime_text(text)
        if parsed is None:
            return None
        return OcrReading(
            text=text,
            device_ts_us=parsed.device_ts_us,
            pattern=parsed.pattern,
            confidence=confidence,
            bbox=bbox,
            engine=self.name,
        )

    def locate(self, image: Image.Image) -> OcrReading | None:
        gray = np.asarray(image.convert("L"))
        best: OcrReading | None = None
        for bbox in iter_candidate_bboxes(gray):
            reading = self.read_crop(image, bbox)
            if reading is not None and (best is None or reading.confidence > best.confidence):
                best = reading
        return best


def default_engines() -> list[OcrEngine]:
    """The standard fallback chain, in order (docs/03-AI-TIMELINE.md §4)."""
    return [PaddleEngine(), RapidEngine(), TesseractEngine(), TemplateEngine()]


# --------------------------------------------------------------------------
# OsdReader: runs the chain, records which engine ran, reuses bboxes
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EngineAttempt:
    engine: str
    available: bool
    reason: str
    matched: bool


@dataclass(frozen=True, slots=True)
class OsdResult:
    reading: OcrReading | None
    attempts: list[EngineAttempt]


class OsdReader:
    """Tries each engine in order; records which one ran (or why each
    unavailable/failed one was skipped) — docs/03-AI-TIMELINE.md §4 step 4
    and §9's "Engine fallback" acceptance row.
    """

    def __init__(self, engines: Sequence[OcrEngine] | None = None) -> None:
        default = default_engines()
        self.engines: list[OcrEngine] = list(engines) if engines is not None else default

    def read(self, image: Image.Image, bbox_hint: BBox | None = None) -> OsdResult:
        attempts: list[EngineAttempt] = []
        for engine in self.engines:
            ok, reason = engine.available()
            if not ok:
                attempts.append(
                    EngineAttempt(engine=engine.name, available=False, reason=reason, matched=False)
                )
                continue

            reading: OcrReading | None = None
            try:
                if bbox_hint is not None:
                    reading = engine.read_crop(image, bbox_hint)
                if reading is None:
                    reading = engine.locate(image)
            except Exception as exc:  # noqa: BLE001 - fallback chain must never hard-fail
                attempts.append(
                    EngineAttempt(
                        engine=engine.name, available=True, reason=f"raised {exc!r}", matched=False
                    )
                )
                continue

            if reading is not None:
                attempts.append(
                    EngineAttempt(engine=engine.name, available=True, reason=reason, matched=True)
                )
                return OsdResult(reading=reading, attempts=attempts)
            attempts.append(
                EngineAttempt(engine=engine.name, available=True, reason=reason, matched=False)
            )
        return OsdResult(reading=None, attempts=attempts)

    def read_sequence(self, images: Sequence[Image.Image]) -> list[OsdResult]:
        """Discover the OSD bbox on the first successful read, then reuse
        it (crop-only) on subsequent frames; re-discovers on a miss.
        """
        results: list[OsdResult] = []
        bbox: BBox | None = None
        for image in images:
            result = self.read(image, bbox_hint=bbox)
            bbox = result.reading.bbox if result.reading is not None else None
            results.append(result)
        return results


# --------------------------------------------------------------------------
# OSD offset (docs §4 step 4: osd_offset = median(osd_ts - header_ts))
# --------------------------------------------------------------------------

#: docs/03-AI-TIMELINE.md §4 step 4: worth naming as a drift once past this.
OSD_DRIFT_NOTEWORTHY_THRESHOLD_S = 1.0


def compute_osd_offset(pairs: Sequence[tuple[int, int]]) -> tuple[int | None, float]:
    """``pairs`` is ``(osd_ts_us, header_ts_us)`` per sampled frame.

    Returns ``(median_offset_us, residual_ms)`` via
    :func:`pramaan_timeline.clock.robust_median_offset` over
    ``osd_ts - header_ts`` (MAD outliers removed).
    """
    diffs = [osd_ts - header_ts for osd_ts, header_ts in pairs]
    return robust_median_offset(diffs)


def describe_osd_drift(osd_offset_us: int, channel: int | None = None) -> str | None:
    """A human sentence for a noteworthy OSD drift, or ``None`` if it's
    within :data:`OSD_DRIFT_NOTEWORTHY_THRESHOLD_S`."""
    offset_s = osd_offset_us / 1_000_000
    if abs(offset_s) <= OSD_DRIFT_NOTEWORTHY_THRESHOLD_S:
        return None
    sign = "+" if offset_s >= 0 else ""
    where = f"channel {channel}" if channel is not None else "this channel"
    return f"camera OSD on {where} differs from recorder clock by {sign}{offset_s:.1f} s"
