"""HTML → PDF (docs/02-BACKEND.md §9 step 2).

WeasyPrint is the primary backend. On macOS/Homebrew, WeasyPrint's native
library loader (cffi ``dlopen``) needs ``libgobject``/``libpango`` findable
via ``DYLD_LIBRARY_PATH`` — Homebrew installs them under ``/opt/homebrew/lib``
but doesn't put that on the default dynamic linker search path. Rather than
require every invocation of this process to be launched with that env var
pre-set, ``_ensure_macos_library_path`` sets it (once, before the first
``import weasyprint``) if it isn't already set and Homebrew's lib dir
exists — verified working in this environment (see docs/progress/B3.md
"Fallbacks used" for the exact probe).

If WeasyPrint still can't be imported/loaded (missing on Linux without the
system pango/cairo packages, e.g. a minimal CI image), this falls back to
headless Chromium via Playwright's ``page.pdf()`` (docs/02-BACKEND.md §9
step 2's documented fallback) — also verified working in this environment.
Both backends produce a real, valid PDF from the same HTML string; which one
ran is returned alongside the bytes so callers can record it (health check,
progress notes) without ever silently producing a broken document.
"""

from __future__ import annotations

import os
import sys
from typing import Literal

PdfBackend = Literal["weasyprint", "playwright-chromium"]


def _ensure_macos_library_path() -> None:
    if sys.platform != "darwin":
        return
    homebrew_lib = "/opt/homebrew/lib"
    if os.path.isdir(homebrew_lib) and homebrew_lib not in os.environ.get(
        "DYLD_LIBRARY_PATH", ""
    ):
        existing = os.environ.get("DYLD_LIBRARY_PATH", "")
        os.environ["DYLD_LIBRARY_PATH"] = (
            f"{homebrew_lib}:{existing}" if existing else homebrew_lib
        )


def _try_weasyprint(html: str, base_url: str | None) -> bytes | None:
    _ensure_macos_library_path()
    try:
        import weasyprint
    except (ImportError, OSError):
        return None
    try:
        result: bytes = weasyprint.HTML(string=html, base_url=base_url).write_pdf()
        return result
    except OSError:
        return None


def _render_with_playwright(html: str, footer_text: str | None) -> bytes:
    # WeasyPrint's own @page margin-box CSS (running header/footer, "Page X
    # of Y" — item 2, docs/progress/FIX-10.md) has no Chromium print-CSS
    # equivalent; Chromium needs its own header/footerTemplate instead, so
    # the fallback backend gets the same running footer via Playwright's
    # API rather than silently shipping a PDF with no footer at all.
    import html as _html

    from playwright.sync_api import sync_playwright

    footer_label = _html.escape(footer_text) if footer_text else "Pramaan"
    footer_template = (
        "<div style='font-family: sans-serif; font-size: 8px; width: 100%; "
        "padding: 0 16mm; color: #5B6479; display: flex; justify-content: space-between;'>"
        f"<span>{footer_label}</span>"
        "<span>Page <span class='pageNumber'></span> of <span class='totalPages'></span></span>"
        "</div>"
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            pdf_bytes: bytes = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "22mm", "bottom": "20mm", "left": "16mm", "right": "16mm"},
                display_header_footer=True,
                header_template="<span></span>",
                footer_template=footer_template,
            )
            return pdf_bytes
        finally:
            browser.close()


def html_to_pdf(
    html: str, *, base_url: str | None = None, footer_text: str | None = None
) -> tuple[bytes, PdfBackend]:
    """Render ``html`` to PDF bytes, returning ``(pdf_bytes, backend_used)``.

    Tries WeasyPrint first; falls back to headless Chromium (Playwright) if
    WeasyPrint's native libraries can't be loaded in this environment.
    ``footer_text`` (e.g. ``"<case number> — report <short hash>"``) is only
    consulted by the Chromium fallback — WeasyPrint gets the equivalent
    running footer from the HTML/CSS itself (``@page`` margin boxes).
    """
    weasy_result = _try_weasyprint(html, base_url)
    if weasy_result is not None:
        return weasy_result, "weasyprint"
    return _render_with_playwright(html, footer_text), "playwright-chromium"


def pdf_backend_available() -> PdfBackend | None:
    """Which backend would be used right now, or ``None`` if neither is
    available (used by ``GET /system/health``)."""
    _ensure_macos_library_path()
    try:
        import weasyprint  # noqa: F401

        return "weasyprint"
    except (ImportError, OSError):
        pass
    try:
        import playwright.sync_api  # noqa: F401

        return "playwright-chromium"
    except ImportError:
        return None
