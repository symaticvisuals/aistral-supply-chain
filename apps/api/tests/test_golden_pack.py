"""Assertions against the real assignment pack.

Skipped when the pack is absent, so the suite still runs on a clean checkout.
Every expected value here was derived by querying the database directly during
design — these exist to catch the layer silently drifting away from the numbers
recorded in DECISIONS.md and the mind map.
"""

import sqlite3
from datetime import date

import pytest

from app.metrics.compute import decompose, fill_numbers, units_short
from app.metrics.fill import (
    attempted_sums,
    ladder,
    max_order_date,
    outlet_rows,
    refused_sums,
)
from app.metrics.quality import all_findings
from app.metrics.scope import SCOPES, get_scope
from app.metrics.windows import parse_window
from app.settings import settings

pytestmark = pytest.mark.skipif(
    not settings.db_path.exists(), reason=f"pack database not at {settings.db_path}"
)


@pytest.fixture(scope="module")
def pack():
    conn = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="module")
def q1(pack):
    return parse_window("fy26q1", max_order_date(pack))


def test_data_window_is_what_the_brief_promised(pack):
    assert max_order_date(pack) == date(2026, 6, 30)


def test_default_window_is_fy26q1(pack):
    w = parse_window(None, max_order_date(pack))
    assert w.id == "fy26q1"
    assert w.is_latest_complete


def test_service_decomposition_matches_the_recorded_numbers(pack, q1):
    s = decompose(attempted_sums(pack, q1), refused_sums(pack, q1, get_scope(None)))
    assert s.execution_pct == pytest.approx(85.89, abs=0.01)
    assert s.availability_pct == pytest.approx(96.71, abs=0.01)
    assert s.service_pct == pytest.approx(83.07, abs=0.01)
    assert s.identity_holds


def test_attempted_only_scope_reproduces_85_89(pack, q1):
    s = decompose(attempted_sums(pack, q1), refused_sums(pack, q1, SCOPES["attempted"]))
    assert s.service_pct == pytest.approx(85.89, abs=0.01)
    assert s.availability_pct == pytest.approx(100.0)


def test_ladder_availability_rungs(pack, q1):
    avail = {r.scope_id: r.availability_pct for r in ladder(pack, q1)}
    assert avail["attempted"] == pytest.approx(100.00, abs=0.01)
    assert avail["stockout"] == pytest.approx(98.28, abs=0.01)
    assert avail["kestrel_fault"] == pytest.approx(96.71, abs=0.01)
    assert avail["all_cancels"] == pytest.approx(93.87, abs=0.01)


def test_execution_never_moves_across_the_ladder(pack, q1):
    execs = [r.execution_pct for r in ladder(pack, q1)]
    assert all(e == pytest.approx(85.89, abs=0.01) for e in execs)


def test_units_short_split(pack, q1):
    u = units_short(attempted_sums(pack, q1), refused_sums(pack, q1, get_scope(None)))
    assert u.shipped_short == pytest.approx(2_014_619, abs=1)
    assert u.never_shipped == pytest.approx(486_144, abs=1)
    assert u.total == pytest.approx(2_500_763, abs=2)


def test_case_only_flatters_the_national_number(pack, q1):
    f = fill_numbers(attempted_sums(pack, q1))
    assert f.case_pct == pytest.approx(85.89, abs=0.01)
    assert f.each_pct == pytest.approx(85.64, abs=0.01)
    assert f.case_only_pct == pytest.approx(84.64, abs=0.01)
    assert f.case_only_lines_dropped > 0


def _overlap(pack, window, scope_id, limit=10):
    rows = outlet_rows(pack, window, SCOPES[scope_id])
    by_units = sorted(rows, key=lambda r: -r.units_short)[:limit]
    by_fill = sorted(
        (r for r in rows if r.case_fill_pct is not None), key=lambda r: r.case_fill_pct
    )[:limit]
    ids = {r.outlet_id for r in by_units}
    return by_units, by_fill, sum(1 for r in by_fill if r.outlet_id in ids)


def test_the_two_worst_lists_are_disjoint_on_attempted_orders(pack, q1):
    by_units, _, overlap = _overlap(pack, q1, "attempted")
    assert overlap == 0

    # The shop no rate-sorted list can ever surface: above the 85.89% national
    # average, and still the largest single hole in the country.
    worst = by_units[0]
    assert worst.units_short > 6_000
    assert worst.case_fill_pct > 85.0


def test_overlap_grows_as_refusals_enter_the_scope(pack, q1):
    """Not a general law — a cancellation damages both measures at once, so the
    two rankings converge once refusals count. Pinned so the claim stays honest.
    """
    overlaps = [
        _overlap(pack, q1, s)[2]
        for s in ("attempted", "stockout", "kestrel_fault", "all_cancels")
    ]
    assert overlaps[0] == 0
    assert overlaps == sorted(overlaps)
    assert overlaps[-1] > overlaps[0]


def test_exposure_gap_between_the_two_lists(pack, q1):
    """Same five calls, twice the units, on attempted orders."""
    by_units, by_fill, _ = _overlap(pack, q1, "attempted", limit=5)
    assert sum(r.units_short for r in by_units) == pytest.approx(29_203, abs=2)
    assert sum(r.units_short for r in by_fill) == pytest.approx(14_531, abs=2)


def test_test_outlets_are_excluded_from_the_pack_numbers(pack, q1):
    """721/722/723 are ACTIVE with 260 orders between them."""
    ids = {r.outlet_id for r in outlet_rows(pack, q1, get_scope(None))}
    assert ids.isdisjoint({721, 722, 723})


def test_quality_findings_report_the_known_blockers(pack, q1):
    findings = {f.id: f for f in all_findings(pack, q1)}
    assert findings["OTIF_IN_FULL_DEGENERATE"].severity == "blocks_metric"
    assert findings["OTIF_IN_FULL_DEGENERATE"].evidence["orders_in_full"] == 0
    assert findings["SHORT_REASON_CODE_NO_SIGNAL"].severity == "blocks_metric"
    assert findings["ORDER_STATUS_NOT_COMPLETENESS"].severity == "advisory"
    assert findings["OPEN_ORDERS_ALREADY_DELIVERED"].severity == "advisory"
    assert findings["ROUTE_REGION_MISMATCH"].severity == "advisory"


def test_the_header_trap_is_reported_as_false(pack, q1):
    """The brief implies headers drift from lines. They do not. Say so."""
    f = {x.id: x for x in all_findings(pack, q1)}["HEADER_TIES_TO_LINES"]
    assert f.severity == "clean"
    assert f.evidence["orders"] == f.evidence["reconciling"]


def test_one_source_system_computes_net_differently(pack, q1):
    f = {x.id: x for x in all_findings(pack, q1)}["NET_VALUE_BY_SOURCE_SYSTEM"]
    assert f.severity == "advisory"
    broken = [s for s in f.evidence["by_source"] if s["reconciling"] < s["n"]]
    assert len(broken) == 1
    assert broken[0]["reconciling"] == 0


def test_order_83511_matches_decisions_md(pack):
    """The worked example recorded in DECISIONS.md, recomputed here."""
    w = parse_window("2026-06-30:2026-06-30", max_order_date(pack))
    row = pack.execute(
        """SELECT
             SUM(CASE WHEN qty_uom='CASE' THEN ordered_qty
                      ELSE ordered_qty/case_pack_at_order END) oc,
             SUM(CASE WHEN qty_uom='CASE' THEN delivered_qty
                      ELSE delivered_qty/case_pack_at_order END) dc,
             SUM(CASE WHEN qty_uom='EACH' THEN ordered_qty
                      ELSE ordered_qty*case_pack_at_order END) oe,
             SUM(CASE WHEN qty_uom='EACH' THEN delivered_qty
                      ELSE delivered_qty*case_pack_at_order END) de
           FROM order_lines WHERE order_id = 83511"""
    ).fetchone()
    assert w.start == date(2026, 6, 30)
    assert 100.0 * row["dc"] / row["oc"] == pytest.approx(83.9, abs=0.05)
    assert 100.0 * row["de"] / row["oe"] == pytest.approx(86.2, abs=0.05)
    assert row["oe"] - row["de"] == pytest.approx(297, abs=1)


def test_excursion_rate_answers_q4_and_says_it_is_flat(pack):
    """Sample question 4, verbatim: excursions per hundred chilled deliveries,
    by month. The series is carried so the question has an answer; the verdict
    is that it does not move, which is why no tile was built for it."""
    finding = next(
        f for f in all_findings(pack, parse_window("fy26q1", max_order_date(pack)))
        if f.id == "EXCURSION_RATE_IS_FLAT"
    )
    assert finding.severity == "advisory"

    months = finding.evidence["by_month"]
    assert len(months) == 18
    rates = [m["per_100"] for m in months]
    # ~22 per hundred, every month for eighteen months.
    assert 20.0 < min(rates) and max(rates) < 24.0
    assert max(rates) - min(rates) < 5.0

    # And no depot stands out either, which kills the "which DC is worst"
    # version of the question too.
    depots = finding.evidence["by_warehouse"]
    assert len(depots) == 8
    assert max(d["per_100"] for d in depots) - min(
        d["per_100"] for d in depots) < 5.0
