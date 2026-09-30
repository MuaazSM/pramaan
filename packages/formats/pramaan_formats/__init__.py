"""Vendor format specs, fingerprints and parsers.

Importing this package registers every built-in :class:`VendorParser`
(``pramaan_formats.base.VendorParser``) with the registry
(``pramaan_formats.registry``), so ``pramaan_formats.registry.get("hiksim")``
works as soon as ``import pramaan_formats`` has run once, anywhere in the
process.
"""

from __future__ import annotations

__version__ = "0.1.0"

# Import for registration side effects (each module decorates its parser
# class with @register). Silence unused-import lint deliberately: this is
# the whole point of these imports.
from pramaan_formats import dhsim as _dhsim  # noqa: F401,E402
from pramaan_formats import hiksim as _hiksim  # noqa: F401,E402
