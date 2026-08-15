"""Fiscal time windows.

Kestrel's financial year runs April-March, so "Q1" means Apr-Jun and calendar
January falls in the *previous* fiscal year's Q4. Getting this wrong quietly
shifts every board number by a quarter.

Naming: a fiscal year is labelled by the calendar year it starts in, so
Apr-Jun 2026 is "FY26 Q1" — the convention already used in understanding.md and
DECISIONS.md. The label is a convention and conventions are arguable, so every
response also carries explicit start and end dates, which are not.
"""

import re
from dataclasses import dataclass
from datetime import date

FY_START_MONTH = 4
_NAMED = re.compile(r"^fy(\d{2})q([1-4])$", re.IGNORECASE)
_RANGE = re.compile(r"^(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})$")


class WindowError(ValueError):
    """The requested window could not be understood. We do not guess."""


@dataclass(frozen=True)
class Window:
    id: str
    label: str
    start: date
    end: date
    is_latest_complete: bool = False


def fiscal_quarter(day: date) -> tuple[int, int]:
    """Return (fiscal year start calendar year, quarter 1-4)."""
    shifted = (day.month - FY_START_MONTH) % 12
    fy_start_year = day.year if day.month >= FY_START_MONTH else day.year - 1
    return fy_start_year, shifted // 3 + 1


def quarter_bounds(fy_start_year: int, quarter: int) -> tuple[date, date]:
    if quarter not in (1, 2, 3, 4):
        raise WindowError(f"Quarter must be 1-4, got {quarter}")
    start_month = FY_START_MONTH + (quarter - 1) * 3
    start = date(fy_start_year + (start_month - 1) // 12, (start_month - 1) % 12 + 1, 1)
    end_month = start_month + 3
    after = date(fy_start_year + (end_month - 1) // 12, (end_month - 1) % 12 + 1, 1)
    return start, date.fromordinal(after.toordinal() - 1)


def _window_for(fy_start_year: int, quarter: int, latest: bool = False) -> Window:
    start, end = quarter_bounds(fy_start_year, quarter)
    yy = fy_start_year % 100
    label = f"FY{yy:02d} Q{quarter} ({start:%b}–{end:%b %Y})"
    return Window(f"fy{yy:02d}q{quarter}", label, start, end, latest)


def latest_complete_quarter(max_date: date) -> Window:
    """The most recent fiscal quarter fully covered by the data.

    A quarter only counts as complete once the data reaches its final day —
    otherwise the board would compare a part-quarter against full ones.
    """
    fy, q = fiscal_quarter(max_date)
    _, end = quarter_bounds(fy, q)
    if max_date < end:
        fy, q = (fy, q - 1) if q > 1 else (fy - 1, 4)
    return _window_for(fy, q, latest=True)


def parse_window(spec: str | None, max_date: date) -> Window:
    """Accept 'fy26q1', an explicit 'YYYY-MM-DD:YYYY-MM-DD' range, or None."""
    if spec is None:
        return latest_complete_quarter(max_date)

    if named := _NAMED.match(spec):
        yy, q = int(named.group(1)), int(named.group(2))
        latest = latest_complete_quarter(max_date)
        window = _window_for(2000 + yy, q)
        return Window(*window.__dict__.values()) if window.id != latest.id else latest

    if ranged := _RANGE.match(spec):
        try:
            start = date.fromisoformat(ranged.group(1))
            end = date.fromisoformat(ranged.group(2))
        except ValueError as exc:
            raise WindowError(f"Not a valid date in {spec!r}") from exc
        if start > end:
            raise WindowError(f"Window starts after it ends: {spec!r}")
        return Window(spec, f"{start:%d %b %Y} – {end:%d %b %Y}", start, end)

    raise WindowError(
        f"Unrecognised window {spec!r}. Use 'fy26q1' or "
        f"'YYYY-MM-DD:YYYY-MM-DD', or omit it for the latest complete quarter."
    )
