"""Pure arithmetic over quantity sums. No database.

Every number here is hand-computable, which is the point: if the SQL is wrong
these still pass, and if these are wrong nothing downstream can be right.
"""

import pytest

from app.metrics.compute import Sums, decompose, fill_numbers, units_short

# One order, two lines, chosen so cases and eaches disagree.
#   line A  CASE  pack 24   ordered 10   delivered  8   -> 10/8 cases, 240/192 eaches
#   line B  EACH  pack 10   ordered 50   delivered 20   ->  5/2 cases,  50/20 eaches
# case fill  = (8 + 2) / (10 + 5)   = 66.666...%
# each fill  = (192 + 20) / (240 + 50) = 73.103...%
# CASE-only  = 8 / 10 = 80%   <- flatters, because it drops line B entirely
ATTEMPTED = Sums(
    ordered_cases=15.0,
    delivered_cases=10.0,
    allocated_cases=12.0,
    ordered_eaches=290.0,
    delivered_eaches=212.0,
    allocated_eaches=250.0,
    case_only_ordered=10.0,
    case_only_delivered=8.0,
    case_only_lines_dropped=1,
    orders=1,
    lines=2,
)

# A refused order: asked for 5 cases / 100 eaches, delivered nothing.
REFUSED = Sums(
    ordered_cases=5.0,
    delivered_cases=0.0,
    allocated_cases=0.0,
    ordered_eaches=100.0,
    delivered_eaches=0.0,
    allocated_eaches=0.0,
    case_only_ordered=5.0,
    case_only_delivered=0.0,
    case_only_lines_dropped=0,
    orders=1,
    lines=1,
)


def test_case_and_each_fill_disagree_on_the_same_rows():
    f = fill_numbers(ATTEMPTED)
    assert f.case_pct == pytest.approx(66.6667, abs=1e-4)
    assert f.each_pct == pytest.approx(73.1034, abs=1e-4)


def test_case_only_flatters_by_dropping_each_lines():
    f = fill_numbers(ATTEMPTED)
    assert f.case_only_pct == pytest.approx(80.0)
    assert f.case_only_pct > f.case_pct
    assert f.case_only_lines_dropped == 1


def test_service_is_exactly_execution_times_availability():
    """The invariant the whole layer rests on.

    If this ever fails, the two factors are not a decomposition of the blend and
    reporting them side by side is a lie.
    """
    s = decompose(ATTEMPTED, REFUSED)
    assert s.service_pct == pytest.approx(
        s.execution_pct * s.availability_pct / 100.0, abs=1e-9
    )
    assert s.identity_holds is True


def test_service_equals_the_naive_blend():
    """Decomposing must not change the number, only explain it."""
    s = decompose(ATTEMPTED, REFUSED)
    blended = 100.0 * ATTEMPTED.delivered_cases / (
        ATTEMPTED.ordered_cases + REFUSED.ordered_cases
    )
    assert s.service_pct == pytest.approx(blended, abs=1e-9)


def test_execution_ignores_refused_orders():
    """Execution is about what we tried to ship; refusals cannot move it."""
    a = decompose(ATTEMPTED, REFUSED).execution_pct
    b = decompose(ATTEMPTED, Sums.zero()).execution_pct
    assert a == pytest.approx(b)


def test_availability_is_100_when_nothing_was_refused():
    s = decompose(ATTEMPTED, Sums.zero())
    assert s.availability_pct == pytest.approx(100.0)
    assert s.service_pct == pytest.approx(s.execution_pct)


def test_units_short_splits_by_cause():
    u = units_short(ATTEMPTED, REFUSED)
    assert u.shipped_short == pytest.approx(78.0)  # 290 - 212
    assert u.never_shipped == pytest.approx(100.0)
    assert u.total == pytest.approx(178.0)


def test_gap_attribution_separates_allocation_from_execution():
    u = units_short(ATTEMPTED, REFUSED)
    assert u.never_reserved == pytest.approx(40.0)  # 290 - 250
    assert u.reserved_not_sent == pytest.approx(38.0)  # 250 - 212
    assert u.never_reserved + u.reserved_not_sent == pytest.approx(u.shipped_short)


def test_empty_scope_yields_null_not_zero():
    """No data and 0% are different claims. Never conflate them."""
    f = fill_numbers(Sums.zero())
    assert f.case_pct is None
    assert f.each_pct is None
    s = decompose(Sums.zero(), Sums.zero())
    assert s.execution_pct is None
    assert s.service_pct is None
