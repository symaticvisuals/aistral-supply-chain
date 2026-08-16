"""Indian FY runs Apr-Mar. Quarters here are fiscal, never calendar."""

from datetime import date

import pytest

from app.metrics.windows import (
    WindowError,
    fiscal_quarter,
    latest_complete_quarter,
    parse_window,
    quarter_bounds,
)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 4, 1), (2026, 1)),  # first day of Q1
        (date(2026, 6, 30), (2026, 1)),  # last day of Q1
        (date(2026, 7, 1), (2026, 2)),  # Q2 starts
        (date(2025, 12, 31), (2025, 3)),  # Q3 of the prior FY
        (date(2026, 1, 15), (2025, 4)),  # Jan is Q4 of the FY that began Apr 2025
        (date(2026, 3, 31), (2025, 4)),  # last day of FY2025-26
    ],
)
def test_fiscal_quarter_boundaries(day, expected):
    assert fiscal_quarter(day) == expected


def test_january_belongs_to_the_previous_fiscal_year():
    """The trap in Apr-Mar: calendar 2026 January is fiscal 2025 Q4."""
    fy, q = fiscal_quarter(date(2026, 1, 1))
    assert (fy, q) == (2025, 4)
    start, end = quarter_bounds(2025, 4)
    assert start == date(2026, 1, 1)
    assert end == date(2026, 3, 31)


def test_quarter_bounds_cover_the_year_without_gaps():
    days = [quarter_bounds(2026, q) for q in (1, 2, 3, 4)]
    assert days[0] == (date(2026, 4, 1), date(2026, 6, 30))
    assert days[3] == (date(2027, 1, 1), date(2027, 3, 31))
    for (_, prev_end), (next_start, _) in zip(days, days[1:], strict=False):
        assert (next_start - prev_end).days == 1


def test_latest_complete_quarter_when_data_ends_exactly_on_a_boundary():
    """The pack ends 2026-06-30, so FY26 Q1 is complete and is the default."""
    w = latest_complete_quarter(date(2026, 6, 30))
    assert w.id == "fy26q1"
    assert (w.start, w.end) == (date(2026, 4, 1), date(2026, 6, 30))


def test_latest_complete_quarter_skips_a_partial_quarter():
    w = latest_complete_quarter(date(2026, 7, 15))
    assert w.id == "fy26q1"


def test_latest_complete_quarter_advances_once_the_next_one_closes():
    w = latest_complete_quarter(date(2026, 9, 30))
    assert w.id == "fy26q2"


def test_parse_named_window():
    w = parse_window("fy26q1", max_date=date(2026, 6, 30))
    assert (w.start, w.end) == (date(2026, 4, 1), date(2026, 6, 30))


def test_parse_explicit_range():
    w = parse_window("2026-05-01:2026-05-31", max_date=date(2026, 6, 30))
    assert (w.start, w.end) == (date(2026, 5, 1), date(2026, 5, 31))
    assert w.id == "2026-05-01:2026-05-31"


def test_parse_default_is_latest_complete():
    assert parse_window(None, max_date=date(2026, 6, 30)).id == "fy26q1"


@pytest.mark.parametrize("spec", ["fy26q5", "garbage", "2026-13-01:2026-12-01", ""])
def test_bad_window_is_rejected_not_guessed(spec):
    with pytest.raises(WindowError):
        parse_window(spec, max_date=date(2026, 6, 30))


def test_inverted_range_is_rejected():
    with pytest.raises(WindowError):
        parse_window("2026-06-30:2026-04-01", max_date=date(2026, 6, 30))
