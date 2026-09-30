"""Bundled font assets (docs/02-BACKEND.md §9 step 2: "fonts bundled
locally"). Geist Sans/Mono variable fonts are copied from ``apps/web/public/
fonts`` into this package (task B3 instruction) so the PDF renderer never
depends on network access or the web app's own build output.
"""

from __future__ import annotations

import base64
from functools import cache
from importlib import resources

GEIST_SANS_FILE = "Geist-Variable.woff2"
GEIST_MONO_FILE = "GeistMono-Variable.woff2"


@cache
def font_data_uri(filename: str) -> str:
    """``data:font/woff2;base64,...`` URI for a bundled font file — embedded
    directly in the rendered HTML's ``@font-face`` rules so WeasyPrint/
    Playwright never needs a filesystem or network font lookup.
    """
    data = resources.files("pramaan_reporting").joinpath("assets", "fonts", filename).read_bytes()
    return f"data:font/woff2;base64,{base64.b64encode(data).decode('ascii')}"
