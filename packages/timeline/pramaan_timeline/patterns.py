"""Date-time pattern parser for OSD text (docs/03-AI-TIMELINE.md §4 step 4).

Recognises the formats named in the spec: ISO ``YYYY-MM-DD HH:MM:SS``,
``DD-MM-YYYY HH:MM:SS`` and ``MM/DD/YYYY HH:MM:SS``, each in 24h or 12h
(``AM``/``PM``) form, with an optional leading or trailing weekday
abbreviation (``Mon``..``Sun``).

All timestamps are computed in UTC (see ``pramaan_timeline.clock``'s module
docstring for why) — the OSD only ever encodes a *device*-local wall-clock
reading; turning that into true/reference time is the four-clock model's
job (``pramaan_timeline.clock``), not this parser's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

_WEEKDAY = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
_AMPM = r"(?:AM|PM|am|pm)"


@dataclass(frozen=True, slots=True)
class ParsedDatetime:
    """A date-time recognised inside a larger string of OCR/OSD text."""

    device_ts_us: int
    pattern: str
    matched_text: str


def _to_24h(hour: int, ampm: str | None) -> int:
    if ampm is None:
        return hour
    ampm = ampm.upper()
    if ampm == "AM":
        return 0 if hour == 12 else hour
    return 12 if hour == 12 else hour + 12


def _make_device_ts_us(
    year: int, month: int, day: int, hour: int, minute: int, second: int
) -> int | None:
    try:
        dt = datetime(year, month, day, hour, minute, second, tzinfo=UTC)
    except ValueError:
        return None
    return int(dt.timestamp() * 1_000_000)


# Patterns are tried in order; the first one that both matches the text and
# yields a valid calendar date/time wins.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "iso_ymd",
        re.compile(
            rf"(?:{_WEEKDAY}\s+)?(?P<y>\d{{4}})-(?P<mo>\d{{2}})-(?P<d>\d{{2}})"
            rf"[ T](?P<h>\d{{1,2}}):(?P<mi>\d{{2}}):(?P<s>\d{{2}})"
            rf"(?:\s*(?P<ampm>{_AMPM}))?(?:\s+{_WEEKDAY})?"
        ),
    ),
    (
        "dmy",
        re.compile(
            rf"(?:{_WEEKDAY}\s+)?(?P<d>\d{{2}})-(?P<mo>\d{{2}})-(?P<y>\d{{4}})"
            rf"\s+(?P<h>\d{{1,2}}):(?P<mi>\d{{2}}):(?P<s>\d{{2}})"
            rf"(?:\s*(?P<ampm>{_AMPM}))?(?:\s+{_WEEKDAY})?"
        ),
    ),
    (
        "mdy",
        re.compile(
            rf"(?:{_WEEKDAY}\s+)?(?P<mo>\d{{2}})/(?P<d>\d{{2}})/(?P<y>\d{{4}})"
            rf"\s+(?P<h>\d{{1,2}}):(?P<mi>\d{{2}}):(?P<s>\d{{2}})"
            rf"(?:\s*(?P<ampm>{_AMPM}))?(?:\s+{_WEEKDAY})?"
        ),
    ),
)


def parse_datetime_text(text: str) -> ParsedDatetime | None:
    """Search ``text`` for the first recognised date-time pattern.

    Returns ``None`` if no pattern matches, or the matched numbers are not
    a valid calendar date/time (e.g. month 13, day 32).
    """
    for name, regex in _PATTERNS:
        match = regex.search(text)
        if match is None:
            continue
        groups = match.groupdict()
        hour = _to_24h(int(groups["h"]), groups.get("ampm"))
        ts = _make_device_ts_us(
            int(groups["y"]),
            int(groups["mo"]),
            int(groups["d"]),
            hour,
            int(groups["mi"]),
            int(groups["s"]),
        )
        if ts is None:
            continue
        return ParsedDatetime(device_ts_us=ts, pattern=name, matched_text=match.group(0))
    return None
