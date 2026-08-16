"""The morning queue. Events with owners, not a frozen quarterly rate."""

import datetime as dt
import sqlite3

import pytest

from app.metrics.morning import (
    case_priority,
    latest_day,
    morning,
    parse_arrival,
    resolve_as_of,
)
from app.settings import settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025-01-02 06:58:00", dt.datetime(2025, 1, 2, 6, 58)),  # TELEMATICS_A
        ("01-Apr-2025 01:00 PM", dt.datetime(2025, 4, 1, 13, 0)),  # TELEMATICS_B
        ("01-Apr-2025 12:00 AM", dt.datetime(2025, 4, 1, 0, 0)),  # midnight, not noon
    ],
)
def test_both_vendor_timestamp_formats_parse(raw, expected):
    assert parse_arrival(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "not a date", "32-Xxx-2025 01:00 PM"])
def test_unparseable_arrival_is_none_not_a_crash(raw):
    """A vendor we have not seen must degrade, not take the morning down."""
    assert parse_arrival(raw) is None


def test_as_of_defaults_to_the_last_day_with_data(conn):
    assert resolve_as_of(conn, None) == latest_day(conn)


def test_as_of_accepts_an_explicit_day(conn):
    assert resolve_as_of(conn, "2026-05-01") == dt.date(2026, 5, 1)


def test_as_of_rejects_junk_rather_than_guessing(conn):
    with pytest.raises(ValueError):
        resolve_as_of(conn, "yesterday")


def test_a_quiet_day_produces_no_events(conn):
    """Silence is a valid answer. An empty queue must not invent work."""
    result = morning(conn, dt.date(2026, 5, 20))
    assert result["events"] == []
    assert result["day"]["orders"] == 0
    # Standing items must not leak into the day list and make a quiet day look
    # busy. Both of these were true before the morning started: stock on a rack
    # and credit notes nobody has ruled on.
    assert [e["kind"] for e in result["standing"]] == [
        "expiring_stock", "credit_backlog",
    ]


def test_morning_reports_the_day_it_was_asked_for(conn):
    result = morning(conn, dt.date(2026, 5, 1))
    assert result["as_of"] == "2026-05-01"
    assert result["is_latest"] is False


def test_cold_chain_ignores_the_vendor_flag_and_reads_the_thermometer(conn):
    """DN0001 is flagged but rode at 3.1C with ambient stock — not an excursion.
    DN0002 is unflagged, carried chilled stock at 12.4C — that is the one."""
    event = next(
        e for e in morning(conn, dt.date(2026, 5, 2))["events"]
        if e["kind"] == "cold_chain"
    )
    assert [i["ref"] for i in event["items"]] == ["DN0002"]

    # And on DN0001's own day the flag must not conjure an event at all.
    kinds = {e["kind"] for e in morning(conn, dt.date(2026, 5, 1))["events"]}
    assert "cold_chain" not in kinds


def test_priority_tiers_are_assigned_per_case(conn):
    """A DC late on most of its drops is a decision; one late drop is a trend."""
    assert case_priority("late_delivery", {"late_pct": 60.0}) == "decide"
    assert case_priority("late_delivery", {"late_pct": 20.0}) == "pattern"
    # Duration is unknown between 8 and 12C, so that is a look, not a write-off.
    assert case_priority("cold_chain", {"max_temp_c": 16.0}) == "act"
    assert case_priority("cold_chain", {"max_temp_c": 9.0}) == "decide"
    # A SKU short at many shops is one fix that clears all of them.
    assert case_priority("sku_short", {"shops": 6}) == "act"
    assert case_priority("sku_short", {"shops": 2}) == "pattern"
    # Supply can still ship a stockout; only finance can lift a credit hold.
    assert case_priority("stockout_refusal", {}) == "act"
    assert case_priority("credit_refusal", {}) == "decide"


def test_morning_names_the_days_the_calendar_may_open(conn):
    result = morning(conn, dt.date(2026, 5, 1))
    assert result["earliest"] == "2026-03-15"
    assert result["latest"] == "2026-05-08"


# ---------------------------------------------------------------- real pack

pack = pytest.mark.skipif(
    not settings.db_path.exists(), reason="pack database not present"
)


@pytest.fixture(scope="module")
def real():
    c = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


@pack
def test_divyas_morning_on_15_april(real):
    """The worked example: what 14 Apr 2026 actually put on her desk."""
    result = morning(real, dt.date(2026, 4, 14))
    kinds = {e["kind"]: e for e in result["events"]}

    assert kinds["cold_chain"]["severity"] == "breach"
    # 19 chilled loads rode above 8C; 3 of them above 12C are write-offs.
    assert kinds["cold_chain"]["population"] == 19
    assert kinds["cold_chain"]["act_now"] == 3
    # The API hands over every case; the screen decides how many to show first.
    # Truncating here would hide work behind a number nobody could open.
    assert len(kinds["cold_chain"]["items"]) == 19

    # The whole reason cold chain is computed rather than read: the vendor flag
    # caught none of the loads we surface. If this ever passes trivially because
    # the flag started working, that is a finding, not a broken test.
    assert all(i["vendor_flag"] == 0 for i in kinds["cold_chain"]["items"])

    # The excursion that arrived early is a vehicle fault, and says so.
    early = [i for i in kinds["cold_chain"]["items"] if i["delay_minutes"] <= 0]
    assert early and "not the schedule" in early[0]["note"]

    # Stockouts are hers; the credit hold is finance's.
    assert kinds["stockout_refusal"]["owner"] == "Supply chain"
    assert kinds["credit_refusal"]["owner"] == "Finance"
    assert kinds["credit_refusal"]["severity"] == "watch"

    # One SKU short at many shops is the high-leverage line.
    assert kinds["sku_short"]["items"][0]["shops"] >= 5


@pack
def test_the_queue_is_ordered_by_what_this_morning_can_change(real):
    """Act tiers first, then decide. Never the other way round."""
    events = morning(real, dt.date(2026, 4, 14))["events"]
    ranks = [{"act": 0, "decide": 1, "pattern": 2}[e["priority"]] for e in events]
    assert ranks == sorted(ranks)

    # A credit hold is finance's decision, so it can never outrank a stockout
    # we could still ship this morning.
    kinds = [e["kind"] for e in events]
    assert kinds.index("stockout_refusal") < kinds.index("credit_refusal")


@pack
def test_a_category_inherits_its_worst_case(real):
    """Cold chain holds both tiers; the category must show the worse one."""
    cc = next(
        e for e in morning(real, dt.date(2026, 4, 14))["events"]
        if e["kind"] == "cold_chain"
    )
    tiers = {i["priority"] for i in cc["items"]}
    assert tiers == {"act", "decide"}
    assert cc["priority"] == "act"
    # And the act cases sort above the decide ones inside the category.
    assert [i["priority"] for i in cc["items"]] == sorted(
        (i["priority"] for i in cc["items"]), key=lambda p: {"act": 0, "decide": 1}[p]
    )


@pack
def test_lateness_is_grouped_by_warehouse_not_route(real):
    """Route grain gave 47 unactionable items; there are only 8 DCs."""
    event = next(
        e for e in morning(real, dt.date(2026, 4, 14))["events"]
        if e["kind"] == "late_delivery"
    )
    assert len(event["items"]) <= 8
    assert {"warehouse", "late", "drops", "late_pct"} <= event["items"][0].keys()


@pack
def test_both_late_sources_are_reported_because_they_disagree(real):
    """delay_minutes and the timestamps differ on a third of all deliveries."""
    day = morning(real, dt.date(2026, 4, 14))["day"]
    assert day["late_over_2h_by_delay_field"] == 31
    assert day["late_over_2h_by_timestamps"] == 59
    assert day["late_over_2h_by_delay_field"] != day["late_over_2h_by_timestamps"]


@pack
def test_default_as_of_is_the_last_day_of_the_pack(real):
    assert resolve_as_of(real, None) == dt.date(2026, 6, 30)
    assert morning(real, dt.date(2026, 6, 30))["is_latest"] is True
