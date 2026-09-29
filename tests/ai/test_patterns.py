"""Unit tests for the date-time pattern parser
(docs/03-AI-TIMELINE.md §4 step 4: ``YYYY-MM-DD HH:MM:SS``,
``DD-MM-YYYY``, ``MM/DD/YYYY``, 12/24h, with weekday variants)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pramaan_timeline.patterns import parse_datetime_text


class TestParseDatetimeText:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("2026-03-12 16:45:12", datetime(2026, 3, 12, 16, 45, 12, tzinfo=UTC)),
            (
                "Frame at 2026-03-12 16:45:12 captured",
                datetime(2026, 3, 12, 16, 45, 12, tzinfo=UTC),
            ),
            ("Thu 2026-03-12 16:45:12", datetime(2026, 3, 12, 16, 45, 12, tzinfo=UTC)),
            ("12-03-2026 04:45:12 PM", datetime(2026, 3, 12, 16, 45, 12, tzinfo=UTC)),
            ("12-03-2026 04:45:12 AM", datetime(2026, 3, 12, 4, 45, 12, tzinfo=UTC)),
            ("03/12/2026 16:45:12", datetime(2026, 3, 12, 16, 45, 12, tzinfo=UTC)),
            ("03/12/2026 12:00:00 AM", datetime(2026, 3, 12, 0, 0, 0, tzinfo=UTC)),
            ("03/12/2026 12:00:00 PM", datetime(2026, 3, 12, 12, 0, 0, tzinfo=UTC)),
            ("2026-03-12T16:45:12", datetime(2026, 3, 12, 16, 45, 12, tzinfo=UTC)),
        ],
    )
    def test_recognises_formats(self, text: str, expected: datetime) -> None:
        parsed = parse_datetime_text(text)
        assert parsed is not None
        assert parsed.device_ts_us == int(expected.timestamp() * 1_000_000)

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "no date here",
            "2026-13-12 16:45:12",  # invalid month
            "2026-03-32 16:45:12",  # invalid day
        ],
    )
    def test_rejects_invalid_or_absent(self, text: str) -> None:
        assert parse_datetime_text(text) is None

    def test_first_matching_pattern_wins(self) -> None:
        parsed = parse_datetime_text("2026-03-12 16:45:12")
        assert parsed is not None
        assert parsed.pattern == "iso_ymd"
