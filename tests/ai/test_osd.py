"""OSD reader tests (docs/03-AI-TIMELINE.md §4 step 4, §9's "OSD" and
"Engine fallback" acceptance rows).

Images are rendered with PIL using the same font the synthetic corpus
generator (tools/synthdvr, Q1) is told to use — DejaVu Sans Mono
(docs/05-INFRA-QA.md §4.1) — bundled at
``pramaan_timeline/assets/DejaVuSansMono.ttf`` (see docs/progress/A1.md
"Decisions" for the font-choice reconciliation note for A2/Q1).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from pramaan_timeline.osd import (
    ASSET_FONT_PATH,
    BBox,
    OcrReading,
    OsdReader,
    PaddleEngine,
    RapidEngine,
    TemplateEngine,
    TesseractEngine,
    compute_osd_offset,
    default_engines,
    describe_osd_drift,
)

DEFAULT_TEXT = "2026-03-12 16:45:12"


def render_osd(
    font_size: int,
    position: tuple[int, int],
    *,
    text: str = DEFAULT_TEXT,
    label: str | None = "CH3 Gate",
    label_position: tuple[int, int] = (20, 20),
    bg: tuple[int, int, int] = (10, 10, 10),
    fg: tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """Render a synthetic OSD frame, sized so ``text`` never clips."""
    font = ImageFont.truetype(str(ASSET_FONT_PATH), font_size)
    text_width = int(font.getlength(text)) + 40
    width = max(position[0] + text_width, 640)
    height = max(position[1] + font_size + 40, 360)
    img = Image.new("RGB", (width, height), color=bg)
    draw = ImageDraw.Draw(img)
    if label is not None:
        draw.text(label_position, label, font=font, fill=fg)
    draw.text(position, text, font=font, fill=fg)
    return img


class TestTemplateEngineAcrossSizesAndPositions:
    """Acceptance: "OSD tests on generated images rendered with the corpus
    font (PIL) at several positions/sizes"."""

    @pytest.mark.parametrize("font_size", [14, 18, 24, 28, 32, 40])
    @pytest.mark.parametrize(
        "position",
        [(300, 20), (300, 150), (50, 250), (400, 260)],
        ids=["top_right", "mid", "bottom_left", "bottom_right"],
    )
    def test_decodes_exact_text_and_timestamp(
        self, font_size: int, position: tuple[int, int]
    ) -> None:
        img = render_osd(font_size, position)
        engine = TemplateEngine(font_size=font_size)
        reading = engine.locate(img)

        assert reading is not None, f"nothing found at size={font_size} pos={position}"
        assert reading.text == DEFAULT_TEXT
        assert reading.engine == "template"

        import datetime as dt

        expected = dt.datetime(2026, 3, 12, 16, 45, 12, tzinfo=dt.UTC)
        assert reading.device_ts_us == int(expected.timestamp() * 1_000_000)

    def test_read_crop_on_known_bbox(self) -> None:
        img = render_osd(24, (300, 20))
        engine = TemplateEngine(font_size=24)
        located = engine.locate(img)
        assert located is not None
        reread = engine.read_crop(img, located.bbox)
        assert reread is not None
        assert reread.text == DEFAULT_TEXT

    def test_available_is_always_true(self) -> None:
        ok, reason = TemplateEngine().available()
        assert ok is True
        assert "guaranteed" in reason or "template" in reason

    def test_unavailable_when_font_path_does_not_exist(self, tmp_path: Path) -> None:
        missing = tmp_path / "no-such-font.ttf"
        ok, reason = TemplateEngine(font_path=missing).available()
        assert ok is False
        assert "font" in reason


class TestTesseractEngine:
    def test_available_on_this_dev_machine(self) -> None:
        # Tesseract 5.5.1 is installed system-wide per docs/progress/W0.1.md's
        # doctor table; this asserts the *positive* path actually runs, not
        # just that unavailability is reported.
        ok, reason = TesseractEngine().available()
        assert ok is True
        assert "tesseract" in reason.lower()

    def test_locate_reads_full_frame(self) -> None:
        img = render_osd(28, (300, 20))
        reading = TesseractEngine().locate(img)
        assert reading is not None
        assert "2026-03-12" in reading.text
        assert reading.device_ts_us is not None

    def test_read_crop_reads_known_region(self) -> None:
        img = render_osd(28, (300, 20))
        located = TesseractEngine().locate(img)
        assert located is not None
        reread = TesseractEngine().read_crop(img, located.bbox)
        assert reread is not None
        assert reread.pattern == "iso_ymd"


class TestOptionalEnginesReportClearReasons:
    """docs §9: "Forcing each OCR engine off falls back to the next
    without failure"; on this disk-constrained dev machine, PaddleOCR and
    RapidOCR are *never* installed (declared under optional extras
    `just setup` does not install — docs/progress/A1.md), so their
    unavailability is exercised for real, not simulated."""

    def test_paddle_engine_reason(self) -> None:
        ok, reason = PaddleEngine().available()
        if ok:
            pytest.skip("paddleocr unexpectedly installed in this environment")
        assert "paddleocr" in reason
        assert "optional" in reason

    def test_rapid_engine_reason(self) -> None:
        ok, reason = RapidEngine().available()
        if ok:
            pytest.skip("rapidocr_onnxruntime unexpectedly installed in this environment")
        assert "rapidocr" in reason
        assert "optional" in reason


class _FixedEngine:
    """A stub `OcrEngine` for exercising `OsdReader`'s fallback logic
    without depending on which real engines happen to be installed."""

    def __init__(
        self,
        name: str,
        *,
        available: bool = True,
        reason: str = "stub",
        reading: OcrReading | None = None,
        raises: bool = False,
    ) -> None:
        self.name = name
        self._available = available
        self._reason = reason
        self._reading = reading
        self._raises = raises
        self.locate_calls = 0
        self.read_crop_calls = 0

    def available(self) -> tuple[bool, str]:
        return self._available, self._reason

    def locate(self, image: Image.Image) -> OcrReading | None:
        self.locate_calls += 1
        if self._raises:
            raise RuntimeError("boom")
        return self._reading

    def read_crop(self, image: Image.Image, bbox: BBox) -> OcrReading | None:
        self.read_crop_calls += 1
        if self._raises:
            raise RuntimeError("boom")
        return self._reading


_REAL_READING = OcrReading(
    text=DEFAULT_TEXT,
    device_ts_us=1_773_333_912_000_000,
    pattern="iso_ymd",
    confidence=0.9,
    bbox=(0, 0, 1, 1),
    engine="fake",
)


class TestOsdReaderFallbackChain:
    def test_default_engines_are_in_spec_order(self) -> None:
        names = [engine.name for engine in default_engines()]
        assert names == ["paddleocr", "rapidocr", "tesseract", "template"]

    def test_skips_unavailable_engines_with_reason_and_tries_next(self) -> None:
        unavailable = _FixedEngine("first", available=False, reason="not installed here")
        working = _FixedEngine("second", reading=_REAL_READING)
        reader = OsdReader(engines=[unavailable, working])

        result = reader.read(Image.new("RGB", (10, 10)))

        assert result.reading is _REAL_READING
        assert result.attempts[0].available is False
        assert result.attempts[0].reason == "not installed here"
        assert result.attempts[0].matched is False
        assert result.attempts[1].matched is True
        assert working.locate_calls == 1

    def test_engine_that_raises_falls_back_without_failing(self) -> None:
        """An engine can be *available* but blow up at read time (e.g. a
        real PaddleOCR/RapidOCR runtime error) — the chain must not
        propagate that; it must record the failure and keep going."""
        broken = _FixedEngine("broken", available=True, raises=True)
        template = TemplateEngine(font_size=28)
        img = render_osd(28, (300, 20))
        reader = OsdReader(engines=[broken, template])

        result = reader.read(img)

        assert result.reading is not None
        assert result.reading.engine == "template"
        assert "raised" in result.attempts[0].reason

    def test_template_matcher_path_runs_when_everything_else_is_disabled(self) -> None:
        """Acceptance: "the template matcher path must run"."""
        img = render_osd(28, (300, 20))
        reader = OsdReader(engines=[TemplateEngine(font_size=28)])
        result = reader.read(img)
        assert result.reading is not None
        assert result.reading.engine == "template"
        assert result.reading.text == DEFAULT_TEXT
        assert len(result.attempts) == 1
        assert result.attempts[0].matched is True

    def test_full_default_chain_finds_a_reading_on_this_machine(self) -> None:
        """End-to-end: whichever engines are actually available on this
        machine (Tesseract at minimum, per docs/progress/W0.1.md), the
        chain as a whole must succeed on a clean rendered frame."""
        img = render_osd(28, (300, 20))
        reader = OsdReader()
        result = reader.read(img)
        assert result.reading is not None
        assert result.reading.engine in {"paddleocr", "rapidocr", "tesseract", "template"}
        matched_names = [a.engine for a in result.attempts if a.matched]
        assert matched_names == [result.reading.engine]

    def test_read_uses_crop_when_bbox_hint_given(self) -> None:
        engine = _FixedEngine("stub", reading=_REAL_READING)
        reader = OsdReader(engines=[engine])
        img = Image.new("RGB", (10, 10))
        reader.read(img, bbox_hint=(0, 0, 5, 5))
        assert engine.read_crop_calls == 1
        assert engine.locate_calls == 0

    def test_read_sequence_discovers_once_and_reuses_bbox(self) -> None:
        images: Sequence[Image.Image] = [render_osd(28, (300, 20)) for _ in range(3)]
        reader = OsdReader(engines=[TemplateEngine(font_size=28)])

        results = reader.read_sequence(images)

        assert all(r.reading is not None for r in results)
        assert all(r.reading.text == DEFAULT_TEXT for r in results)  # type: ignore[union-attr]
        bboxes = {r.reading.bbox for r in results}  # type: ignore[union-attr]
        assert len(bboxes) == 1  # same bbox rediscovered/reused every time

    def test_read_sequence_rediscovers_after_a_miss(self) -> None:
        blank = Image.new("RGB", (200, 100), color=(0, 0, 0))
        good = render_osd(28, (300, 20))
        reader = OsdReader(engines=[TemplateEngine(font_size=28)])

        results = reader.read_sequence([blank, good])

        assert results[0].reading is None
        assert results[1].reading is not None
        assert results[1].reading.text == DEFAULT_TEXT


class TestOsdOffset:
    def test_compute_offset_from_pairs(self) -> None:
        header_base = 1_000_000_000
        pairs = [
            (header_base + 37_000_000, header_base),
            (header_base + 37_020_000, header_base),
            (header_base + 36_990_000, header_base),
        ]
        offset_us, residual_ms = compute_osd_offset(pairs)
        assert offset_us is not None
        assert abs(offset_us - 37_000_000) < 50_000

    def test_describe_drift_above_threshold(self) -> None:
        message = describe_osd_drift(37_000_000, channel=2)
        assert message is not None
        assert "+37.0" in message
        assert "channel 2" in message

    def test_describe_drift_below_threshold_is_none(self) -> None:
        assert describe_osd_drift(200_000) is None

    def test_describe_negative_drift(self) -> None:
        message = describe_osd_drift(-5_000_000)
        assert message is not None
        assert "-5.0" in message
