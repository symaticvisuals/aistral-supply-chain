"""Scope decides which rows count. Every exclusion must be provable and named."""

import pytest

from app.metrics.compute import decompose, units_short
from app.metrics.fill import attempted_sums, ladder, refused_sums
from app.metrics.scope import (
    SCOPES,
    ScopeError,
    build_receipt,
    get_scope,
)


def test_attempted_sums_match_the_hand_computed_fixture(conn, window):
    s = attempted_sums(conn, window)
    assert s.orders == 2
    assert s.ordered_cases == pytest.approx(15.0)
    assert s.delivered_cases == pytest.approx(10.0)
    assert s.ordered_eaches == pytest.approx(290.0)
    assert s.delivered_eaches == pytest.approx(212.0)
    assert s.allocated_eaches == pytest.approx(280.0)


def test_test_closed_and_deleted_outlets_never_enter_the_numbers(conn, window):
    """Each carries a 100-case 0%-fill order; a leak would crater execution."""
    s = attempted_sums(conn, window)
    assert s.ordered_cases == pytest.approx(15.0)  # not 115, 215 or 315
    assert decompose(s, refused_sums(conn, window, SCOPES["attempted"])
                     ).execution_pct == pytest.approx(200.0 / 3)


def test_orders_outside_the_window_are_excluded(conn, window):
    """Order 9 sits in March, one quarter earlier, with a 100-case ask."""
    assert attempted_sums(conn, window).orders == 2


def test_default_scope_counts_stockout_but_not_closed_or_duplicate(conn, window):
    refused = refused_sums(conn, window, get_scope(None))
    assert refused.orders == 1  # order 3 only, not order 4
    assert refused.ordered_cases == pytest.approx(5.0)


def test_attempted_scope_refuses_nothing(conn, window):
    assert refused_sums(conn, window, SCOPES["attempted"]).orders == 0


def test_all_cancels_scope_picks_up_the_non_fault_cancellation(conn, window):
    refused = refused_sums(conn, window, SCOPES["all_cancels"])
    assert refused.orders == 2
    assert refused.ordered_cases == pytest.approx(8.0)  # 5 + 3


def test_open_orders_are_excluded_from_every_scope(conn, window):
    """OPEN is 85.8% delivered in the real data, so including it raises fill."""
    for scope in SCOPES.values():
        total = (
            attempted_sums(conn, window).orders
            + refused_sums(conn, window, scope).orders
        )
        assert total <= 4  # orders 1,2,3,4 at most — never order 5


def test_service_decomposition_on_the_fixture(conn, window):
    attempted = attempted_sums(conn, window)
    refused = refused_sums(conn, window, get_scope(None))
    s = decompose(attempted, refused)
    assert s.execution_pct == pytest.approx(200.0 / 3)  # 10/15
    assert s.availability_pct == pytest.approx(75.0)  # 15/20
    assert s.service_pct == pytest.approx(50.0)
    assert s.identity_holds


def test_units_short_splits_shipped_from_never_shipped(conn, window):
    u = units_short(
        attempted_sums(conn, window), refused_sums(conn, window, get_scope(None))
    )
    assert u.shipped_short == pytest.approx(78.0)
    assert u.never_shipped == pytest.approx(120.0)  # 5 cases x 24
    assert u.total == pytest.approx(198.0)


def test_execution_is_constant_across_every_ladder_rung(conn, window):
    """The finding that reshaped the design: only availability moves."""
    rungs = ladder(conn, window)
    executions = {round(r.execution_pct, 9) for r in rungs}
    assert len(executions) == 1
    availabilities = [r.availability_pct for r in rungs]
    assert availabilities == sorted(availabilities, reverse=True)
    assert availabilities[0] == pytest.approx(100.0)


def test_receipt_names_every_excluded_outlet(conn, window):
    receipt = build_receipt(conn, window, get_scope(None))
    names = {o["outlet_name"] for o in receipt.excluded_outlets}
    assert names == {"ZZ_TEST_OUTLET", "Closed Shop", "Deleted Shop"}
    reasons = {o["reason"] for o in receipt.excluded_outlets}
    assert "test_or_migration_row" in reasons
    assert "outlet_deleted" in reasons
    assert "outlet_closed" in reasons


def test_receipt_counts_excluded_orders_by_reason(conn, window):
    receipt = build_receipt(conn, window, get_scope(None))
    assert receipt.orders_excluded["status_open"] == 1
    assert receipt.orders_excluded["cancelled_cr02_outlet_closed"] == 1
    assert "cancelled_cr03_no_stock" not in receipt.orders_excluded
    assert receipt.total_orders_excluded >= 5


def test_credit_hold_is_flagged_as_contested(conn):
    assert get_scope("kestrel_fault").contested == ("CR01_CREDIT",)
    assert get_scope("stockout").contested == ()


def test_unknown_scope_raises_rather_than_defaulting(conn):
    with pytest.raises(ScopeError):
        get_scope("whatever_looks_best")


def test_region_filter_narrows_to_that_region(conn, window):
    assert attempted_sums(conn, window, region_id=1).orders == 2
    assert attempted_sums(conn, window, region_id=2).orders == 0
