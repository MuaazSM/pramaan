"""Vendor parser registry (docs/01-FORENSIC-CORE.md §4.5:
"Registry: ``pramaan_formats.registry.get(family)``").

Thin re-export of :mod:`pramaan_formats.base`'s registry functions under the
module path the spec names, so callers don't need to know that the
:class:`~pramaan_formats.base.VendorParser` protocol and the registry live
in the same module.
"""

from __future__ import annotations

from pramaan_formats.base import UnknownFamily, VendorParser, available_families, get, register

__all__ = ["UnknownFamily", "VendorParser", "available_families", "get", "register"]
