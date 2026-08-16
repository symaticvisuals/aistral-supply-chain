"""Credit notes against dispatch value.

Fixture numbers are computed on paper in the comments so a failure says which
definition moved, not just that a total changed.
"""

import sqlite3
from datetime import date

import pytest

from app.metrics import money
from app.metrics.fill import max_order_date
from app.metrics.windows import parse_window
from app.settings import settings

# Outlet 101 is the only outlet that survives the filter. In the FY26 Q1 window
# its delivered quantities, priced at 1000/ordered per line:
#   order 1  delivered  8 of 10 @ 100.0      =  800.000
#   order 2  delivered 20 of 50 @  20.0      =  400.000
#   order 3  delivered  0 of  5              =    0.000   (cancelled)
#   order 4  delivered  0 of  3              =    0.000   (cancelled)
#   order 5  delivered  6 of  7 @ 142.857…   =  857.143   (OPEN, but it shipped)
#   order 9  outside the window              =    0.000
EXPECTED_DISPATCH = 800.0 + 400.0 + 6 * (1000.0 / 7)


def test_dispatch_value_prices_what_shipped(conn, window):
    assert money.dispatch_value(conn, window) == pytest.approx(EXPECTED_DISPATCH)


def test_dispatch_value_is_not_the_line_value_column(conn, window):
    """line_value_inr prices the ordered quantity; dispatch must be lower."""
    billed = conn.execute(
        """SELECT SUM(ol.line_value_inr) AS v
             FROM order_lines ol JOIN orders o ON o.order_id = ol.order_id
             JOIN outlets ot ON ot.outlet_id = o.outlet_id
            WHERE o.order_date BETWEEN ? AND ? AND ot.outlet_id = 101""",
        (window.start.isoformat(), window.end.isoformat()),
    ).fetchone()["v"]
    assert money.dispatch_value(conn, window) < billed


def test_credit_notes_split_by_status(conn, window):
    # CN1 approved 5000, CN2 pending 3000, CN3 rejected 2000.
    # CN4 is before the window; CN5 belongs to the test outlet.
    notes = money.credit_notes(conn, window)
    assert (notes.settled_inr, notes.undecided_inr, notes.refused_inr) == (
        5000.0, 3000.0, 2000.0,
    )
    assert (notes.settled_n, notes.undecided_n, notes.refused_n) == (1, 1, 1)
    assert notes.exposed_inr == 8000.0
    assert notes.raised_inr == 10000.0


def test_test_outlet_credit_note_never_counted(conn, window):
    """CN5 is worth 9999 on ZZ_TEST_OUTLET. If the filter leaks, this shouts."""
    assert money.credit_notes(conn, window).raised_inr == 10000.0


def test_notes_before_the_window_are_excluded(conn, window):
    assert money.credit_notes(conn, window).undecided_inr == 3000.0


def test_pending_queue_ignores_the_window(conn):
    """CN4 is 13 months older than the window and is exactly what must show up."""
    q = money.pending_queue(conn, date(2026, 6, 30))
    assert q.notes_n == 2
    assert q.value_inr == 4000.0
    assert q.oldest_date == date(2025, 6, 1)
    assert q.oldest_days == 394


def test_pending_queue_counts_what_has_gone_stale(conn):
    """CN4 is 394 days old (stale), CN2 is 50 (not). Off-by-one in the SQL args
    silently shifts these, so both sides of the threshold are asserted."""
    q = money.pending_queue(conn, date(2026, 6, 30))
    assert q.stale_n == 1
    assert q.stale_inr == 1000.0
    assert q.notes_n == 2 and q.value_inr == 4000.0


def test_pending_work_list_is_ordered_by_value_not_age(conn):
    """The oldest note is the smallest. Age-sorting would bury the real money."""
    rows = money.pending_to_work(conn, date(2026, 6, 30))
    assert [r["ref"] for r in rows] == ["CN2", "CN4"]
    assert [r["days_waiting"] for r in rows] == [50, 394]


def test_leakage_ratio_uses_dispatch_not_billings(conn, window):
    leak = money.leakage(conn, window)
    assert leak.raised_pct == pytest.approx(100.0 * 10000.0 / EXPECTED_DISPATCH)
    assert leak.exposed_pct == pytest.approx(100.0 * 8000.0 / EXPECTED_DISPATCH)
    assert leak.settled_pct == pytest.approx(100.0 * 5000.0 / EXPECTED_DISPATCH)


def test_ratio_is_none_not_zero_when_nothing_shipped(conn):
    """A window with no dispatch has no ratio. None and 0.0 are different claims."""
    empty = parse_window("2020-01-01:2020-01-31", max_date=date(2026, 6, 30))
    leak = money.leakage(conn, empty)
    assert leak.dispatch_inr == 0
    assert leak.raised_pct is None
    assert leak.material is False


def test_by_category_ranks_on_settled_plus_undecided(conn, window):
    rows = money.by_category(conn, window)
    assert [r.category for r in rows] == ["Dairy", "Staples"]
    assert rows[0].settled_inr == 5000.0        # CN1, chilled product
    assert rows[1].undecided_inr == 3000.0      # CN2
    assert rows[1].refused_inr == 2000.0        # CN3


def test_region_filter_applies(conn, window):
    """Every fixture outlet is in region 1, so region 2 must come back empty."""
    assert money.credit_notes(conn, window, region_id=2).raised_inr == 0.0
    assert money.dispatch_value(conn, window, region_id=2) == 0


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
def test_pack_q1_credit_notes(pack):
    w = parse_window("fy26q1", max_order_date(pack))
    leak = money.leakage(pack, w)
    assert leak.dispatch_inr == pytest.approx(2_348_770_426, rel=1e-6)
    assert leak.notes.settled_inr == pytest.approx(652_739, rel=1e-4)
    assert leak.notes.undecided_inr == pytest.approx(363_479, rel=1e-4)
    assert leak.notes.refused_inr == pytest.approx(403_606, rel=1e-4)
    # 0.06% of dispatch — the reason the screen ranks on rupees, not on this.
    assert leak.raised_pct == pytest.approx(0.0604, abs=5e-4)
    assert leak.material is False


@pack_only
def test_pack_pending_queue_is_stale(pack):
    w = parse_window("fy26q1", max_order_date(pack))
    q = money.pending_queue(pack, w.end)
    assert q.notes_n == 2865
    assert q.value_inr == pytest.approx(1_882_588, rel=1e-4)
    assert q.oldest_days == 542


@pack_only
def test_pack_categories_are_flat(pack):
    """No category dominates: the top is under 2x the bottom on exposed value."""
    rows = money.by_category(pack, parse_window("fy26q1", max_order_date(pack)))
    exposed = [r.settled_inr + r.undecided_inr for r in rows]
    assert len(rows) == 8
    assert max(exposed) < 2 * min(exposed)
