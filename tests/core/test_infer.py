"""Format inference against the real XSIM corpus image
(docs/01-FORENSIC-CORE.md §4.8 acceptance: "magic, header length, channel,
timestamp (with unit and endianness), length and sequence all found with
confidence >= 0.9 ... >= 99% of ground-truth frames recovered with correct
channel and timestamp").

**Blind-inference rule**: this file never reads ``docs/05-INFRA-QA.md``
§4.6, ``tools/synthdvr/pramaan_synthdvr/writers/xsim.py``, or the
``hidden_layout`` key of ``corpus/truth/xsim_*.json``. It measures frame
recall against ``corpus/truth/xsim_unknown.frames.parquet`` by
``payload_offset``/``payload_len`` only (the columns docs/01-FORENSIC-CORE.md
§4.8's acceptance explicitly allows CORE to use) and asserts internal
consistency of the *discovered* layout (every required field present at
confidence >= 0.9) — it never compares against ``hidden_layout`` itself;
that field-by-field comparison is QA's job (a later task).
``tests/validation/test_no_xsim_leak.py`` is the enforcement mechanism that
this module's own source never leaks the magic.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest
from pramaan_core.evidence import EvidenceReader
from pramaan_recovery import infer

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = REPO_ROOT / "corpus" / "images"
TRUTH_DIR = REPO_ROOT / "corpus" / "truth"

RECALL_FLOOR = 0.99
REQUIRED_FIELDS = {"channel", "timestamp", "length", "sequence"}
FIELD_CONFIDENCE_FLOOR = 0.9


def _skip_if_missing() -> None:
    if not (IMAGES_DIR / "xsim_unknown.img").exists():
        pytest.skip("corpus/images/xsim_unknown.img not generated yet — run `just corpus` first")


@pytest.mark.slow
def test_infer_layout_discovers_every_required_field_with_high_confidence() -> None:
    _skip_if_missing()
    with EvidenceReader.open(str(IMAGES_DIR / "xsim_unknown.img")) as r:
        layout = infer.infer_layout(r)

    assert layout is not None, "inference found no layout at all on xsim_unknown.img"
    assert layout.magic is not None
    assert layout.header_len > 0

    found_by_name = {f.name: f for f in layout.fields}
    missing = REQUIRED_FIELDS - found_by_name.keys()
    assert not missing, f"required field(s) not discovered: {missing}"
    for name in REQUIRED_FIELDS:
        f = found_by_name[name]
        assert f.confidence >= FIELD_CONFIDENCE_FLOOR, (
            f"field {name!r} confidence {f.confidence:.2f} below {FIELD_CONFIDENCE_FLOOR}"
        )

    # Internal consistency: fields fit inside the header and don't overlap.
    spans = sorted((f.offset, f.offset + f.width, f.name) for f in layout.fields)
    pairs = zip(spans, spans[1:], strict=False)
    for (_a_start, a_end, a_name), (b_start, _b_end, _b_name) in pairs:
        assert a_end <= layout.header_len, f"field {a_name} extends past header_len"
        assert a_end <= b_start, f"fields overlap: {spans}"

    timestamp_field = found_by_name["timestamp"]
    assert timestamp_field.unit in ("s", "ms", "us")


@pytest.mark.slow
def test_infer_layout_is_deterministic() -> None:
    _skip_if_missing()
    with EvidenceReader.open(str(IMAGES_DIR / "xsim_unknown.img")) as r:
        layout_a = infer.infer_layout(r)
        layout_b = infer.infer_layout(r)
    assert layout_a is not None and layout_b is not None
    assert layout_a.model_dump() == layout_b.model_dump()
    assert layout_a.id == layout_b.id


@pytest.mark.slow
def test_inferred_parser_recovers_at_least_99_percent_of_frames_with_correct_channel_and_ts() -> (
    None
):
    _skip_if_missing()
    truth = pq.read_table(TRUTH_DIR / "xsim_unknown.frames.parquet").to_pylist()
    assert truth

    with EvidenceReader.open(str(IMAGES_DIR / "xsim_unknown.img")) as r:
        layout = infer.infer_layout(r)
        assert layout is not None
        parser = infer.InferredParser(layout)
        frames = list(parser.iter_frames(r, "img_test"))

    frames_by_offset = {f.payload_offset: f for f in frames}
    recovered_correct = 0
    for t in truth:
        f = frames_by_offset.get(t["payload_offset"])
        if f is None:
            continue
        if f.channel == t["channel"] and f.ts_header_us == t["ts_device_us"]:
            recovered_correct += 1
    fraction = recovered_correct / len(truth)
    assert fraction >= RECALL_FLOOR, (
        f"only {fraction:.1%} of ground-truth frames recovered with correct channel+timestamp"
    )
    for f in frames:
        assert f.source == "inferred"
        assert not f.deleted


@pytest.mark.slow
def test_summarize_layout_mentions_every_field(tmp_path: Path) -> None:
    _skip_if_missing()
    with EvidenceReader.open(str(IMAGES_DIR / "xsim_unknown.img")) as r:
        layout = infer.infer_layout(r)
    assert layout is not None
    summary = infer.summarize_layout(layout)
    assert f"{layout.header_len}-byte header" in summary
    for f in layout.fields:
        assert f.name in summary


@pytest.mark.slow
def test_emit_ksy_writes_a_draft_spec(tmp_path: Path) -> None:
    _skip_if_missing()
    with EvidenceReader.open(str(IMAGES_DIR / "xsim_unknown.img")) as r:
        layout = infer.infer_layout(r)
    assert layout is not None
    path = infer.emit_ksy(layout, tmp_path)
    assert path.exists()
    text = path.read_text()
    assert "meta:" in text
    assert "seq:" in text


def test_infer_layout_returns_none_on_a_tiny_garbage_image(tmp_path: Path) -> None:
    img = tmp_path / "tiny.img"
    img.write_bytes(b"\x00\x01\x02" * 10)
    with EvidenceReader.open(str(img)) as r:
        assert infer.infer_layout(r) is None
