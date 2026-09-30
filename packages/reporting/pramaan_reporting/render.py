"""Jinja2 HTML rendering (docs/02-BACKEND.md §9 step 2)."""

from __future__ import annotations

from importlib import resources
from typing import Any

from jinja2 import Environment, FunctionLoader

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


_ENV = Environment(loader=FunctionLoader(_load_template), autoescape=True)
_ENV.filters["shorthash"] = _shorthash
_ENV.filters["fmt_us"] = _fmt_us


def render_report_html(context: dict[str, Any]) -> str:
    template = _ENV.get_template("report.html")
    return template.render(css=print_css(), **context)


def render_certificate_html(context: dict[str, Any]) -> str:
    template = _ENV.get_template("certificate.html")
    return template.render(css=print_css(), **context)
