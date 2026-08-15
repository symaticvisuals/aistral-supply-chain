"""SQL for fill. Returns totals; app.metrics.compute turns them into rates.

Three tables only — order_lines, orders, outlets. `deliveries` is deliberately
absent: it answers on-time, not in-full, and in-full is uncomputable on this
data anyway (see quality.OTIF_IN_FULL_DEGENERATE).
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from app.metrics.compute import Sums, decompose, fill_numbers, units_short
from app.metrics.scope import (
    LADDER_ORDER,
    SCOPES,
    Scope,
    attempted_filter,
    outlet_filter,
    refused_filter,
)
from app.metrics.windows import Window

# One line's quantities expressed in both units. case_pack_at_order is read from
# the line, not the product master: it is a snapshot of pack size at order time,
# so it stays correct even after a SKU is repacked.
_CASES_ORDERED = """
  CASE WHEN ol.qty_uom = 'CASE' THEN ol.ordered_qty
       ELSE ol.ordered_qty / ol.case_pack_at_order END"""
_CASES_DELIVERED = """
  CASE WHEN ol.qty_uom = 'CASE' THEN ol.delivered_qty
       ELSE ol.delivered_qty / ol.case_pack_at_order END"""
_CASES_ALLOCATED = """
  CASE WHEN ol.qty_uom = 'CASE' THEN ol.allocated_qty
       ELSE ol.allocated_qty / ol.case_pack_at_order END"""
_EACHES_ORDERED = """
  CASE WHEN ol.qty_uom = 'EACH' THEN ol.ordered_qty
       ELSE ol.ordered_qty * ol.case_pack_at_order END"""
_EACHES_DELIVERED = """
  CASE WHEN ol.qty_uom = 'EACH' THEN ol.delivered_qty
       ELSE ol.delivered_qty * ol.case_pack_at_order END"""
_EACHES_ALLOCATED = """
  CASE WHEN ol.qty_uom = 'EACH' THEN ol.allocated_qty
       ELSE ol.allocated_qty * ol.case_pack_at_order END"""

_SUM_COLUMNS = f"""
  COALESCE(SUM({_CASES_ORDERED}), 0)    AS ordered_cases,
  COALESCE(SUM({_CASES_DELIVERED}), 0)  AS delivered_cases,
  COALESCE(SUM({_CASES_ALLOCATED}), 0)  AS allocated_cases,
  COALESCE(SUM({_EACHES_ORDERED}), 0)   AS ordered_eaches,
  COALESCE(SUM({_EACHES_DELIVERED}), 0) AS delivered_eaches,
  COALESCE(SUM({_EACHES_ALLOCATED}), 0) AS allocated_eaches,
  COALESCE(SUM(CASE WHEN ol.qty_uom = 'CASE' THEN ol.ordered_qty END), 0)
    AS case_only_ordered,
  COALESCE(SUM(CASE WHEN ol.qty_uom = 'CASE' THEN ol.delivered_qty END), 0)
    AS case_only_delivered,
  COALESCE(SUM(CASE WHEN ol.qty_uom <> 'CASE' THEN 1 ELSE 0 END), 0)
    AS case_only_lines_dropped,
  COUNT(DISTINCT o.order_id) AS orders,
  COUNT(*) AS lines"""

_FROM = """
  FROM order_lines ol
  JOIN orders o   ON o.order_id = ol.order_id
  JOIN outlets ot ON ot.outlet_id = o.outlet_id"""


def max_order_date(conn: sqlite3.Connection) -> date:
    """Latest order in the data. Windows derive from this, never from today()."""
    row = conn.execute("SELECT MAX(order_date) AS d FROM orders").fetchone()
    if not row or not row["d"]:
        raise RuntimeError("No orders in the database")
    return date.fromisoformat(row["d"][:10])


def _sums(
    conn: sqlite3.Connection,
    window: Window,
    order_predicate: str,
    region_id: int | None,
) -> Sums:
    args: list[object] = [window.start.isoformat(), window.end.isoformat()]
    region_clause = ""
    if region_id is not None:
        region_clause = "AND o.region_id = ?"
        args.append(region_id)

    row = conn.execute(
        f"""SELECT {_SUM_COLUMNS} {_FROM}
            WHERE o.order_date BETWEEN ? AND ? {region_clause}
              AND {outlet_filter()}
              AND ({order_predicate})""",
        args,
    ).fetchone()
    return Sums(
        ordered_cases=row["ordered_cases"],
        delivered_cases=row["delivered_cases"],
        allocated_cases=row["allocated_cases"],
        ordered_eaches=row["ordered_eaches"],
        delivered_eaches=row["delivered_eaches"],
        allocated_eaches=row["allocated_eaches"],
        case_only_ordered=row["case_only_ordered"],
        case_only_delivered=row["case_only_delivered"],
        case_only_lines_dropped=row["case_only_lines_dropped"],
        orders=row["orders"],
        lines=row["lines"],
    )


def attempted_sums(conn, window: Window, region_id: int | None = None) -> Sums:
    return _sums(conn, window, attempted_filter(), region_id)


def refused_sums(conn, window: Window, scope: Scope, region_id=None) -> Sums:
    return _sums(conn, window, refused_filter(scope), region_id)


@dataclass(frozen=True)
class Rung:
    scope_id: str
    label: str
    execution_pct: float | None
    availability_pct: float | None
    service_pct: float | None
    shipped_short: float
    never_shipped: float


def ladder(conn, window: Window, region_id: int | None = None) -> list[Rung]:
    """Every scope side by side.

    Execution is identical on every rung by construction — it only ever looks at
    attempted orders. That is the point: the scope argument moves availability
    and nothing else, which is invisible when you only publish the blend.
    """
    attempted = attempted_sums(conn, window, region_id)
    rungs = []
    for scope_id in LADDER_ORDER:
        scope = SCOPES[scope_id]
        refused = refused_sums(conn, window, scope, region_id)
        service = decompose(attempted, refused)
        short = units_short(attempted, refused)
        rungs.append(
            Rung(
                scope_id=scope_id,
                label=scope.label,
                execution_pct=service.execution_pct,
                availability_pct=service.availability_pct,
                service_pct=service.service_pct,
                shipped_short=short.shipped_short,
                never_shipped=short.never_shipped,
            )
        )
    return rungs


@dataclass(frozen=True)
class OutletRow:
    outlet_id: int
    outlet_name: str
    city: str
    channel: str
    orders: int
    case_fill_pct: float | None
    each_fill_pct: float | None
    units_asked: float
    units_short: float


def outlet_rows(
    conn, window: Window, scope: Scope, region_id: int | None = None
) -> list[OutletRow]:
    """Per-outlet totals across the scope's full row set.

    Refused orders contribute their ask and nothing delivered, so an outlet whose
    orders were cancelled for stockout shows the damage rather than vanishing.
    """
    args: list[object] = [window.start.isoformat(), window.end.isoformat()]
    region_clause = ""
    if region_id is not None:
        region_clause = "AND o.region_id = ?"
        args.append(region_id)

    rows = conn.execute(
        f"""
        SELECT ot.outlet_id, ot.outlet_name, ot.city, ot.channel,
               COUNT(DISTINCT o.order_id) AS orders,
               COALESCE(SUM({_CASES_ORDERED}), 0)    AS oc,
               COALESCE(SUM({_CASES_DELIVERED}), 0)  AS dc,
               COALESCE(SUM({_EACHES_ORDERED}), 0)   AS oe,
               COALESCE(SUM({_EACHES_DELIVERED}), 0) AS de
        {_FROM}
        WHERE o.order_date BETWEEN ? AND ? {region_clause}
          AND {outlet_filter()}
          AND (({attempted_filter()}) OR ({refused_filter(scope)}))
        GROUP BY ot.outlet_id, ot.outlet_name, ot.city, ot.channel
        """,
        args,
    ).fetchall()

    out = []
    for r in rows:
        f = fill_numbers(
            Sums(r["oc"], r["dc"], 0.0, r["oe"], r["de"], 0.0, 0.0, 0.0, 0, 0, 0)
        )
        out.append(
            OutletRow(
                outlet_id=r["outlet_id"],
                outlet_name=r["outlet_name"],
                city=r["city"],
                channel=r["channel"],
                orders=r["orders"],
                case_fill_pct=f.case_pct,
                each_fill_pct=f.each_pct,
                units_asked=r["oe"],
                units_short=r["oe"] - r["de"],
            )
        )
    return out
