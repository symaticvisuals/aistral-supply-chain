"""Stock that will not sell before it expires.

Fixture values are computed in conftest's comment so a failure names the
definition that moved, not just a total that changed.
"""

import sqlite3
from datetime import date

import pytest

from app.metrics import expiry
from app.settings import settings

AS_OF = date(2026, 5, 1)


def test_uses_the_snapshot_as_it_was_known_that_morning(conn):
    """Never a later snapshot: the morning of the 1st cannot see the 8th."""
    assert expiry.latest_snapshot(conn, AS_OF) == date(2026, 5, 1)
    assert expiry.latest_snapshot(conn, date(2026, 4, 30)) == date(2026, 4, 24)
    assert expiry.latest_snapshot(conn, date(2024, 1, 1)) is None


def test_stock_before_any_snapshot_is_empty_not_an_error(conn):
    risk = expiry.at_risk(conn, date(2024, 1, 1))
    assert risk.lines == []
    assert risk.snapshot_date is None
    assert risk.is_stale is True


def test_only_the_current_snapshot_counts(conn):
    """B004 is 999 cases expiring tomorrow — on last week's snapshot. If the
    query forgets to pin the date, this shouts."""
    batches = {line.batch for line in expiry.at_risk(conn, AS_OF).lines}
    assert "B004" not in batches


def test_healthy_stock_is_not_listed(conn):
    """B003 has 214 days left and five days of cover. Nothing to say about it."""
    batches = {line.batch for line in expiry.at_risk(conn, AS_OF).lines}
    assert "B003" not in batches


def test_cannot_sell_through_is_cover_against_days_left(conn):
    risk = expiry.at_risk(conn, AS_OF)
    by_batch = {line.batch: line for line in risk.lines}

    # B001: 35 days of cover, 20 days left -> arithmetic says it cannot move.
    assert by_batch["B001"].cannot_sell is True
    assert by_batch["B001"].days_left == 20
    # 100 cases x 24 per case x Rs 50 each
    assert by_batch["B001"].value_inr == pytest.approx(120_000)

    # B002 expires just as soon, but five days of cover clears it in time.
    assert by_batch["B002"].cannot_sell is False
    assert by_batch["B002"].value_inr == pytest.approx(60_000)


def test_the_two_readings_are_counted_separately(conn):
    """Near expiry is the wide watch list; cannot-sell is the sharp one."""
    risk = expiry.at_risk(conn, AS_OF)
    assert risk.near_lines == 2          # B001 and B002 both expire in 20 days
    assert risk.doomed_lines == 1        # only B001 cannot move in time
    assert risk.doomed_value_inr == pytest.approx(120_000)
    assert risk.near_value_inr == pytest.approx(180_000)


def test_cannot_sell_sorts_above_merely_near(conn):
    """B002 is worth less but that is not why it is second — it will sell."""
    lines = expiry.at_risk(conn, AS_OF).lines
    assert [line.batch for line in lines] == ["B001", "B002"]


def test_a_week_old_snapshot_is_flagged_stale(conn):
    """Weekly cadence, so eight days means the count is not the shelf."""
    assert expiry.at_risk(conn, AS_OF).is_stale is False
    later = expiry.at_risk(conn, date(2026, 5, 12))
    assert later.snapshot_date == date(2026, 5, 1)
    assert later.snapshot_age_days == 11
    assert later.is_stale is True


def test_region_filters_on_the_warehouse_not_the_outlet(conn):
    """Stock sits in a DC, so the DC's region is the only one that means
    anything — unlike every other region filter in this service."""
    assert expiry.at_risk(conn, AS_OF, region_id=1).lines
    assert expiry.at_risk(conn, AS_OF, region_id=2).lines == []


# --- against the real pack ------------------------------------------------

pack_only = pytest.mark.skipif(
    not settings.db_path.exists(), reason=f"pack database not at {settings.db_path}"
)


@pytest.fixture(scope="module")
def pack():
    c = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


@pack_only
def test_pack_stock_at_risk_on_30_june(pack):
    risk = expiry.at_risk(pack, date(2026, 6, 30))
    assert risk.snapshot_date == date(2026, 6, 29)
    assert risk.is_stale is False
    assert risk.doomed_lines == 147
    assert risk.doomed_cases == 64_457
    assert risk.doomed_value_inr == pytest.approx(204_001_330, rel=1e-6)
    assert risk.near_lines == 244


@pack_only
def test_pack_nothing_has_already_expired(pack):
    """If negative days-left ever appears, the warehouse has a bigger problem
    than this screen and the number needs its own treatment."""
    risk = expiry.at_risk(pack, date(2026, 6, 30), limit=1000)
    assert all(line.days_left >= 0 for line in risk.lines)
