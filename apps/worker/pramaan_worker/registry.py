"""Import-guarded registries for the CORE parser packages (task B2).

``pramaan_formats`` (fingerprinter, per-vendor ``VendorParser``s),
``pramaan_recovery`` (carver, clip builder) and ``pramaan_logs`` (device log
parser) are being written concurrently by other tasks (C2/C3). Layout
inference (``pramaan_recovery.infer``) and the deletion verdict
(``pramaan_recovery.deletion``) had not landed yet when this module was
written — C3's slice of ``pramaan_recovery`` — while the fingerprinter,
``VendorParser``s (hiksim/dhsim) and carver/clip-builder (C2's slice) had.
Stages 2-9 (``apps/worker/pramaan_worker/stages.py``) must still run
end-to-end regardless of which pieces exist at any given moment, so every
lookup here goes through one place:

1. An in-process override registered via ``register_*`` (this is the hook
   fast tests use: register a small fake ``VendorParser``/fingerprinter/etc
   for the duration of a test, no real package needed).
2. Falling back to a *lazy* import of the real package/attribute. Any
   ``ImportError``/``AttributeError``/``LookupError`` (package absent,
   present but the expected attribute doesn't exist yet, or
   ``pramaan_formats.registry.UnknownFamily`` for a family with no
   registered parser) is swallowed and the lookup returns ``None`` — the
   calling stage then records ``skipped=True, message="<stage>: skipped
   (parser unavailable — ...)"`` and the pipeline continues
   (docs/PROMPTBOOK.md: "a missing package degrades gracefully").

See docs/progress/B2.md "Integration contract" for the exact
function/class signatures this module binds to, and what C3/A2 still need
to add.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol, runtime_checkable

from pramaan_core.evidence import EvidenceReader
from pramaan_core.models import (
    ByteRange,
    DeletionFinding,
    FrameRef,
    InferredLayout,
    LogEvent,
    Recording,
    VendorMatch,
)


@runtime_checkable
class VendorParser(Protocol):
    """Mirrors docs/01-FORENSIC-CORE.md §4.5 / ``pramaan_formats.base.VendorParser``."""

    family: str

    def detect(self, reader: EvidenceReader) -> VendorMatch | None: ...
    def list_recordings(self, reader: EvidenceReader) -> list[Recording]: ...
    def iter_frames(self, reader: EvidenceReader, rec: Recording) -> Iterable[FrameRef]: ...
    def unindexed_ranges(self, reader: EvidenceReader) -> list[ByteRange]: ...
    def index_state(self, reader: EvidenceReader) -> dict[str, Any]: ...


Fingerprinter = Callable[[EvidenceReader], list[VendorMatch]]
#: ``(reader, image_id, ranges) -> list[FrameRef]`` — matches
#: ``pramaan_recovery.carve.carve_annexb`` and
#: ``pramaan_recovery.vendor_carve.carve_dhav``/``carve_hiksim_ps``.
Carver = Callable[[EvidenceReader, str, list[ByteRange]], list[FrameRef]]
LayoutInferrer = Callable[[EvidenceReader], "InferredLayout | None"]
DeletionAnalyzer = Callable[..., list[DeletionFinding]]
#: ``(reader, image_id, channel, frames, out_dir, *, sps_pps_cache=None,
#: max_gap_us=..., parent_sha256=None) -> list[ClipResult]`` — matches
#: ``pramaan_recovery.clip.build_clips``. ``ClipResult`` (a
#: ``pramaan_recovery.clip.ClipResult``-shaped object, structurally) needs
#: ``.clip_id: str``, ``.path: Path``, ``.start_ts_us``/``.end_ts_us: int |
#: None`` and ``.provenance: pramaan_core.models.Provenance``.
ClipBuilder = Callable[..., list[Any]]
LogParser = Callable[[EvidenceReader, str], list[LogEvent]]
#: ``(layout: InferredLayout) -> <object with .iter_frames(reader, image_id)
#: -> Iterator[FrameRef]>`` — matches ``pramaan_recovery.infer.InferredParser``
#: (the class itself is the factory: ``InferredParser(layout)``). Used by the
#: `/inferred-layouts/{lid}/confirm` real-mode reindex (task FIX-1), not by
#: any of the 11 automatic scan stages.
InferredParserFactory = Callable[[InferredLayout], Any]

#: Real per-family vendor carvers (docs/01-FORENSIC-CORE.md §4.7 step 7),
#: dispatched to from :func:`get_carver` when no override is registered.
#: Families with no dedicated carver (e.g. the Tier C ``gensim`` corpus, or
#: any family carve.py's ``carve_annexb`` alone must handle) fall back to
#: the generic carver.
_REAL_VENDOR_CARVER_NAMES: dict[str, str] = {
    "dhsim": "carve_dhav",
    "hiksim": "carve_hiksim_ps",
    "hwsim": "carve_hwsim",
}

_fingerprinter: Fingerprinter | None = None
_vendor_parsers: dict[str, VendorParser] = {}
_generic_carver: Carver | None = None
_vendor_carvers: dict[str, Carver] = {}
_layout_inferrer: LayoutInferrer | None = None
_deletion_analyzer: DeletionAnalyzer | None = None
_clip_builder: ClipBuilder | None = None
_log_parser: LogParser | None = None
_inferred_parser_factory: InferredParserFactory | None = None


def register_fingerprinter(fn: Fingerprinter | None) -> None:
    global _fingerprinter
    _fingerprinter = fn


def register_vendor_parser(parser: VendorParser | None, *, family: str | None = None) -> None:
    """Register (or, with ``parser=None``, unregister) a fake/real parser
    for ``family`` (defaults to ``parser.family``)."""
    if parser is None:
        if family is not None:
            _vendor_parsers.pop(family, None)
        return
    _vendor_parsers[family or parser.family] = parser


def register_generic_carver(fn: Carver | None) -> None:
    global _generic_carver
    _generic_carver = fn


def register_vendor_carver(family: str, fn: Carver | None) -> None:
    if fn is None:
        _vendor_carvers.pop(family, None)
        return
    _vendor_carvers[family] = fn


def register_layout_inferrer(fn: LayoutInferrer | None) -> None:
    global _layout_inferrer
    _layout_inferrer = fn


def register_deletion_analyzer(fn: DeletionAnalyzer | None) -> None:
    global _deletion_analyzer
    _deletion_analyzer = fn


def register_clip_builder(fn: ClipBuilder | None) -> None:
    global _clip_builder
    _clip_builder = fn


def register_log_parser(fn: LogParser | None) -> None:
    global _log_parser
    _log_parser = fn


def register_inferred_parser_factory(fn: InferredParserFactory | None) -> None:
    global _inferred_parser_factory
    _inferred_parser_factory = fn


def reset_for_tests() -> None:
    """Clear every override. Call from a test fixture's teardown."""
    global _fingerprinter, _generic_carver, _layout_inferrer, _deletion_analyzer
    global _clip_builder, _log_parser, _inferred_parser_factory
    _fingerprinter = None
    _vendor_parsers.clear()
    _generic_carver = None
    _vendor_carvers.clear()
    _layout_inferrer = None
    _deletion_analyzer = None
    _clip_builder = None
    _log_parser = None
    _inferred_parser_factory = None


def get_fingerprinter() -> Fingerprinter | None:
    if _fingerprinter is not None:
        return _fingerprinter
    try:
        from pramaan_formats.fingerprint import match

        return match  # type: ignore[no-any-return]
    except (ImportError, AttributeError):
        return None


def get_vendor_parser(family: str) -> VendorParser | None:
    if family in _vendor_parsers:
        return _vendor_parsers[family]
    try:
        from pramaan_formats.registry import get as _get

        return _get(family)  # type: ignore[no-any-return]
    except (ImportError, AttributeError, LookupError):
        return None


def get_carver(family: str | None) -> Carver | None:
    """The best available carver for ``family`` (``None`` = unknown/Tier C):
    an explicit vendor override, else an explicit generic override, else
    the real vendor-specific carver for ``family`` if C2 shipped one, else
    the real generic Annex-B carver, else ``None``.
    """
    if family is not None and family in _vendor_carvers:
        return _vendor_carvers[family]
    if _generic_carver is not None:
        return _generic_carver
    if family is not None and family in _REAL_VENDOR_CARVER_NAMES:
        try:
            from pramaan_recovery import vendor_carve  # type: ignore[import-untyped]

            fn = getattr(vendor_carve, _REAL_VENDOR_CARVER_NAMES[family])
            return fn  # type: ignore[no-any-return]
        except (ImportError, AttributeError):
            pass
    try:
        from pramaan_recovery.carve import carve_annexb  # type: ignore[import-untyped]

        return carve_annexb  # type: ignore[no-any-return]
    except (ImportError, AttributeError):
        return None


def get_layout_inferrer() -> LayoutInferrer | None:
    if _layout_inferrer is not None:
        return _layout_inferrer
    try:
        from pramaan_recovery.infer import infer_layout  # type: ignore[import-untyped]

        return infer_layout  # type: ignore[no-any-return]
    except (ImportError, AttributeError):
        return None


def get_deletion_analyzer() -> DeletionAnalyzer | None:
    if _deletion_analyzer is not None:
        return _deletion_analyzer
    try:
        from pramaan_recovery.deletion import detect_deletions  # type: ignore[import-untyped]

        return detect_deletions  # type: ignore[no-any-return]
    except (ImportError, AttributeError):
        return None


def get_clip_builder() -> ClipBuilder | None:
    """Falls back to :mod:`pramaan_worker.clips`'s own ffmpeg-based clip
    builder (registered lazily by ``stages.clips`` itself) only when
    neither an override nor the real ``pramaan_recovery.clip.build_clips``
    are available.
    """
    if _clip_builder is not None:
        return _clip_builder
    try:
        from pramaan_recovery.clip import build_clips  # type: ignore[import-untyped]

        return build_clips  # type: ignore[no-any-return]
    except (ImportError, AttributeError):
        return None


def get_log_parser() -> LogParser | None:
    if _log_parser is not None:
        return _log_parser
    try:
        from pramaan_logs import parse_logs  # type: ignore[import-untyped]

        return parse_logs  # type: ignore[no-any-return]
    except (ImportError, AttributeError):
        return None


def get_inferred_parser_factory() -> InferredParserFactory | None:
    if _inferred_parser_factory is not None:
        return _inferred_parser_factory
    try:
        from pramaan_recovery.infer import InferredParser

        return InferredParser  # type: ignore[no-any-return]
    except (ImportError, AttributeError):
        return None
