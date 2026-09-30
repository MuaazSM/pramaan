"""Vendor parser interface and registry (docs/01-FORENSIC-CORE.md §4.5).

Every vendor-specific parser implements :class:`VendorParser` and registers
itself under its ``family`` name (matching ``fingerprints.yaml``'s
``family`` and :class:`pramaan_core.models.VendorMatch.family`). Consumers
(BACKEND's pipeline, CORE's carvers/clip builder, tests) look parsers up by
name through :func:`get` rather than importing a concrete class, so a real
vendor parser can later replace a synthetic one behind the same interface
(docs/01-FORENSIC-CORE.md §1, "Honesty rule").
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, ClassVar, Protocol, runtime_checkable

from pramaan_core.evidence import EvidenceReader
from pramaan_core.models import ByteRange, FrameRef, Recording, VendorMatch


@runtime_checkable
class VendorParser(Protocol):
    """One vendor family's parser (docs/01-FORENSIC-CORE.md §4.5)."""

    family: ClassVar[str]

    def detect(self, r: EvidenceReader) -> VendorMatch | None:
        """Confirm/refine the fingerprinter's match by actually parsing the
        header. Returns ``None`` if the image does not look like this
        family once the header is inspected in detail."""
        ...

    def list_recordings(self, r: EvidenceReader) -> list[Recording]:
        """Recordings referenced by the *live* on-disk index only."""
        ...

    def iter_frames(self, r: EvidenceReader, rec: Recording) -> Iterator[FrameRef]:
        """Yield every frame belonging to ``rec``, in disk order."""
        ...

    def unindexed_ranges(self, r: EvidenceReader) -> list[ByteRange]:
        """The data area minus whatever the live index currently covers —
        the search space for carving deleted footage."""
        ...

    def index_state(self, r: EvidenceReader) -> dict[str, Any]:
        """A small dict of index/header metadata useful for the deletion
        verdict (init/format time, declared capacity, write pointer, entry
        counts, ...). Keys are family-specific; values must be
        JSON-serialisable."""
        ...


class UnknownFamily(KeyError):
    """Raised by :func:`get` for a family with no registered parser."""


_REGISTRY: dict[str, type[VendorParser]] = {}


def register(parser_cls: type[VendorParser]) -> type[VendorParser]:
    """Register ``parser_cls`` under its ``family`` name. Usable as a
    decorator; also called directly by this package's ``__init__``."""
    _REGISTRY[parser_cls.family] = parser_cls
    return parser_cls


def get(family: str) -> VendorParser:
    """Return a fresh instance of the parser registered for ``family``."""
    try:
        cls = _REGISTRY[family]
    except KeyError as exc:
        raise UnknownFamily(f"no VendorParser registered for family {family!r}") from exc
    return cls()


def available_families() -> list[str]:
    """Families with a registered parser, sorted for deterministic output."""
    return sorted(_REGISTRY)
