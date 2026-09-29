"""Four-clock normalisation, OCR, correlation."""

from pramaan_timeline.clock import (
    AgreementResult,
    build_clock_model,
    compute_confidence,
    header_index_agreement,
    normalise_frame_table,
    offset_for_device_ts,
    reconstruct_segments,
    robust_median_offset,
)
from pramaan_timeline.osd import (
    ASSET_FONT_PATH,
    BBox,
    EngineAttempt,
    OcrEngine,
    OcrReading,
    OsdReader,
    OsdResult,
    PaddleEngine,
    RapidEngine,
    TemplateEngine,
    TesseractEngine,
    compute_osd_offset,
    default_engines,
    describe_osd_drift,
    find_text_blobs,
    iter_candidate_bboxes,
)
from pramaan_timeline.patterns import ParsedDatetime, parse_datetime_text

__version__ = "0.1.0"

__all__ = [
    "ASSET_FONT_PATH",
    "AgreementResult",
    "BBox",
    "EngineAttempt",
    "OcrEngine",
    "OcrReading",
    "OsdReader",
    "OsdResult",
    "PaddleEngine",
    "ParsedDatetime",
    "RapidEngine",
    "TemplateEngine",
    "TesseractEngine",
    "build_clock_model",
    "compute_confidence",
    "compute_osd_offset",
    "default_engines",
    "describe_osd_drift",
    "find_text_blobs",
    "header_index_agreement",
    "iter_candidate_bboxes",
    "normalise_frame_table",
    "offset_for_device_ts",
    "parse_datetime_text",
    "reconstruct_segments",
    "robust_median_offset",
]
