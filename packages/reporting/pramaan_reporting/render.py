"""Jinja2 HTML rendering (docs/02-BACKEND.md §9 step 2).

``print_css()`` is trusted, generated-in-process CSS (never user input) —
it is wrapped in ``markupsafe.Markup`` before being handed to the template
so Jinja2's autoescaping (correctly on for every other, user/case-derived
value in these templates) does not HTML-escape the CSS's own quote
characters. Un-escaped quotes are load-bearing here: a `"` turned into
`&#34;` inside a `<style>` block silently invalidates every quoted
`font-family`/`url(...)` declaration it appears in, which is why the
bundled Geist fonts previously fell back to the PDF viewer's default serif
font — see docs/progress/FIX-10.md.
"""

from __future__ import annotations

from importlib import resources
from pathlib import PurePosixPath
from typing import Any

from jinja2 import Environment, FunctionLoader
from markupsafe import Markup, escape

from pramaan_reporting.styles import print_css


def _load_template(name: str) -> str:
    return resources.files("pramaan_reporting").joinpath("templates", name).read_text("utf-8")


def _shorthash(value: str | None) -> str:
    """references/BRAND.md §4: "show the first 8 and last 4 characters"."""
    if not value:
        return "—"
    if len(value) <= 14:
        return value
    return f"{value[:8]}…{value[-4:]}"


def _hash_break(value: str | None) -> Markup:
    """A long hex digest (SHA-256, 64 chars), broken into two 32-char lines
    so it can never overflow the printed page's right margin regardless of
    the PDF backend's line-wrapping behaviour (belt-and-braces alongside
    the CSS ``word-break``/``overflow-wrap`` rules in ``styles.py``).
    Shorter values (e.g. 32-char MD5, content ids) pass through unchanged.
    """
    if not value:
        return Markup("—")
    text = str(value)
    if len(text) <= 32:
        return Markup(escape(text))
    return Markup(escape(text[:32])) + Markup("<br>") + Markup(escape(text[32:]))


def _basename(path: str | None) -> str:
    """The bare file name of an evidence path — the rendered report/
    certificate never prints the absolute host filesystem path (item 6,
    docs/progress/FIX-10.md); the full path is only ever offered in the
    appendix, for an examiner who explicitly needs it."""
    if not path:
        return "—"
    name = PurePosixPath(str(path).replace("\\", "/")).name
    return name or str(path)


def _fmt_us(value: int | None) -> str:
    """A device-clock microsecond value as a plain UTC-epoch-relative mono
    string — no timezone claim is made (device clocks are unreliable by
    design here; see manifest limitations)."""
    if value is None:
        return "—"
    from datetime import UTC, datetime

    try:
        dt = datetime.fromtimestamp(value / 1_000_000, tz=UTC)
        return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{value % 1_000_000:06d}"[:3]
    except (OverflowError, OSError, ValueError):
        return str(value)


def _fmt_ts(value: str | None) -> str:
    """A wall-clock ISO-8601 UTC timestamp (as produced by
    ``pramaan_core.timeutil.utc_now_iso``, e.g.
    ``"2026-09-30T03:10:07.754536Z"``), rendered consistently at seconds
    precision in both UTC and IST (item 7, docs/progress/FIX-10.md) —
    microsecond precision is noise to a reader of a legal document, and a
    bare UTC timestamp is easy to misread in an Indian court context."""
    if not value:
        return "—"
    from datetime import UTC, datetime, timedelta, timezone

    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return str(value)
    ist = dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} UTC ({ist.strftime('%Y-%m-%d %H:%M:%S')} IST)"


_ENV = Environment(loader=FunctionLoader(_load_template), autoescape=True)
_ENV.filters["shorthash"] = _shorthash
_ENV.filters["hash_break"] = _hash_break
_ENV.filters["basename"] = _basename
_ENV.filters["fmt_us"] = _fmt_us
_ENV.filters["fmt_ts"] = _fmt_ts


def render_report_html(context: dict[str, Any]) -> str:
    template = _ENV.get_template("report.html")
    return template.render(css=Markup(print_css()), **context)


def render_certificate_html(context: dict[str, Any]) -> str:
    template = _ENV.get_template("certificate.html")
    return template.render(css=Markup(print_css()), **context)
