"""OSD font used by every synthetic recording.

Vendored (not read from the host OS) so the AI OCR-template task (A1) can
render its test images with byte-identical glyphs, and so `just corpus`
does not depend on fonts happening to be installed on the machine.

docs/05-INFRA-QA.md §4.1 asks for "Geist Mono or DejaVu Sans Mono". This
machine's ffmpeg 8.1 build has no libfreetype (the `drawtext` filter is
unavailable — see docs/progress/Q1.md "Fallbacks used"), so OSD frames are
rendered with Pillow instead of ffmpeg's drawtext; DejaVu Sans Mono is
Pillow's bundled-format-compatible TrueType font, permissively licensed
(Bitstream Vera Fonts Copyright, free to embed/redistribute), and was
already present on this machine (via the texlive installation), so it was
copied here rather than downloaded.
"""

from __future__ import annotations

from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT_PATH = FONT_DIR / "DejaVuSansMono.ttf"
FONT_NAME = "DejaVu Sans Mono"

# Point sizes used for OSD text, so AI's OCR template reader matches exactly.
OSD_FONT_SIZE = 16
