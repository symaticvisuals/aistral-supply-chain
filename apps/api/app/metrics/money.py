"""Credit notes against dispatch value.

Divya's third ask is "returns and credit notes as a percentage of dispatch value".
Both halves of that sentence needed a decision.

*Credit notes* and *returns* are one table here, not two: a return produces a
credit note, and `returns_credit_notes` carries both. So this reports one thing,
split by whether the credit desk has actually agreed to pay it.

*Dispatch value* is not a column. `line_value_inr` is ordered quantity times
price on all 511,516 lines — it bills what was asked for, not what went out. With
fill at roughly 86% that overstates dispatch by about a seventh, so the value
shipped is recomputed here from delivered quantity.

What this module deliberately does not offer is a breakdown by reason code. The
codes are noise on this data (see quality.return_reason_signal), and slicing
money by a random label produces confident nonsense.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from app.metrics.compute import pct
from app.metrics.scope import outlet_filter
from app.metrics.windows import Window

# A credit note is only money once someone agrees to pay it. Three states, three
# different numbers, and the gap between them is the whole point of showing all
# three rather than picking one.
SETTLED = ("APPROVED",)
UNDECIDED = ("PENDING",)
REFUSED = ("REJECTED",)

# Below this, the ratio cannot move a decision — it rounds to nothing at every
# grain and every period, so reporting it as a KPI invites false precision.
MATERIAL_PCT = 0.5

# What actually left the building: delivered quantity at line price, after the
# line discount. Never line_value_inr, which is the ordered value.
_DISPATCH_VALUE = """
  ol.delivered_qty * ol.unit_price_inr
    * (1 - COALESCE(ol.line_discount_pct, 0) / 100.0)"""


def _in(values: tuple[str, ...]) -> str:
    """SQL IN list. Not repr() — a one-tuple reprs with a trailing comma."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


_SETTLED_IN = _in(SETTLED)
_UNDECIDED_IN = _in(UNDECIDED)
_REFUSED_IN = _in(REFUSED)


@dataclass(frozen=True)
class CreditNotes:
    settled_inr: float
    undecided_inr: float
    refused_inr: float
    settled_n: int
    undecided_n: int
    refused_n: int

    @property
    def exposed_inr(self) -> float:
        """Agreed plus not-yet-refused. The bill if every open note is allowed."""
        return self.settled_inr + self.undecided_inr

    @property
    def raised_inr(self) -> float:
        return self.settled_inr + self.undecided_inr + self.refused_inr


@dataclass(frozen=True)
class Leakage:
    dispatch_inr: float
    notes: CreditNotes
    settled_pct: float | None
    exposed_pct: float | None
    raised_pct: float | None
    material: bool


@dataclass(frozen=True)
class CategoryRow:
    category: str
    settled_inr: float
    undecided_inr: float
    refused_inr: float
    notes_n: int


# A credit note still undecided after a year is not a queue, it is a process
# that stopped. Tracked separately so the age of the pile is a number, not an
# anecdote about its single oldest row.
STALE_DAYS = 365


@dataclass(frozen=True)
class PendingQueue:
    notes_n: int
    value_inr: float
    oldest_date: date | None
    oldest_days: int | None
    stale_n: int
    stale_inr: float


def _region_clause(region_id: int | None, args: list[object]) -> str:
    if region_id is None:
        return ""
    args.append(region_id)
    return "AND ot.region_id = ?"


def dispatch_value(
    conn: sqlite3.Connection, window: Window, region_id: int | None = None
) -> float:
    """Rupees actually shipped in the window, at line price after discount."""
    args: list[object] = [window.start.isoformat(), window.end.isoformat()]
    clause = _region_clause(region_id, args)
    row = conn.execute(
        f"""SELECT COALESCE(SUM({_DISPATCH_VALUE}), 0) AS v
              FROM order_lines ol
              JOIN orders o   ON o.order_id = ol.order_id
              JOIN outlets ot ON ot.outlet_id = o.outlet_id
             WHERE o.order_date BETWEEN ? AND ? {clause}
               AND {outlet_filter()}""",
        args,
    ).fetchone()
    return row["v"]


def credit_notes(
    conn: sqlite3.Connection, window: Window, region_id: int | None = None
) -> CreditNotes:
    """Credit notes raised in the window, by whether anyone has decided on them."""
    args: list[object] = [window.start.isoformat(), window.end.isoformat()]
    clause = _region_clause(region_id, args)
    row = conn.execute(
        f"""SELECT
              COALESCE(SUM(CASE WHEN r.status IN {_SETTLED_IN}
                                THEN r.credit_note_value_inr END), 0) AS settled,
              COALESCE(SUM(CASE WHEN r.status IN {_UNDECIDED_IN}
                                THEN r.credit_note_value_inr END), 0) AS undecided,
              COALESCE(SUM(CASE WHEN r.status IN {_REFUSED_IN}
                                THEN r.credit_note_value_inr END), 0) AS refused,
              COALESCE(SUM(r.status IN {_SETTLED_IN}), 0)   AS settled_n,
              COALESCE(SUM(r.status IN {_UNDECIDED_IN}), 0) AS undecided_n,
              COALESCE(SUM(r.status IN {_REFUSED_IN}), 0)   AS refused_n
            FROM returns_credit_notes r
            JOIN outlets ot ON ot.outlet_id = r.outlet_id
           WHERE r.return_date BETWEEN ? AND ? {clause}
             AND {outlet_filter()}""",
        args,
    ).fetchone()
    return CreditNotes(
        settled_inr=row["settled"],
        undecided_inr=row["undecided"],
        refused_inr=row["refused"],
        settled_n=row["settled_n"],
        undecided_n=row["undecided_n"],
        refused_n=row["refused_n"],
    )


def leakage(
    conn: sqlite3.Connection, window: Window, region_id: int | None = None
) -> Leakage:
    """The ratio Divya asked for, with all three numerators it could have.

    Dispatch is dated by order and credit notes by return date, so a note here
    can belong to a dispatch in the previous period. That is how period
    accounting works and it is fine over a quarter; over a single day it is not,
    which is why this is a window metric and not a morning tile.
    """
    dispatch = dispatch_value(conn, window, region_id)
    notes = credit_notes(conn, window, region_id)
    settled = pct(notes.settled_inr, dispatch)
    exposed = pct(notes.exposed_inr, dispatch)
    raised = pct(notes.raised_inr, dispatch)
    return Leakage(
        dispatch_inr=dispatch,
        notes=notes,
        settled_pct=settled,
        exposed_pct=exposed,
        raised_pct=raised,
        material=raised is not None and raised >= MATERIAL_PCT,
    )


def by_category(
    conn: sqlite3.Connection, window: Window, region_id: int | None = None
) -> list[CategoryRow]:
    """Where the leak sits by category, in rupees.

    Returned in rupees rather than as a share of each category's own dispatch:
    the categories turn out to sit within a narrow band of each other, and a
    percentage would dress that flatness up as a ranking.
    """
    args: list[object] = [window.start.isoformat(), window.end.isoformat()]
    clause = _region_clause(region_id, args)
    rows = conn.execute(
        f"""SELECT COALESCE(p.category, 'Unknown') AS category,
              COALESCE(SUM(CASE WHEN r.status IN {_SETTLED_IN}
                                THEN r.credit_note_value_inr END), 0) AS settled,
              COALESCE(SUM(CASE WHEN r.status IN {_UNDECIDED_IN}
                                THEN r.credit_note_value_inr END), 0) AS undecided,
              COALESCE(SUM(CASE WHEN r.status IN {_REFUSED_IN}
                                THEN r.credit_note_value_inr END), 0) AS refused,
              COUNT(*) AS n
            FROM returns_credit_notes r
            JOIN outlets ot  ON ot.outlet_id = r.outlet_id
            LEFT JOIN products p ON p.product_id = r.product_id
           WHERE r.return_date BETWEEN ? AND ? {clause}
             AND {outlet_filter()}
           GROUP BY 1""",
        args,
    ).fetchall()
    out = [
        CategoryRow(
            category=r["category"],
            settled_inr=r["settled"],
            undecided_inr=r["undecided"],
            refused_inr=r["refused"],
            notes_n=r["n"],
        )
        for r in rows
    ]
    return sorted(out, key=lambda c: -(c.settled_inr + c.undecided_inr))


def pending_queue(
    conn: sqlite3.Connection, as_of: date, region_id: int | None = None
) -> PendingQueue:
    """Every credit note nobody has decided on, at any age.

    Not windowed. A note raised eighteen months ago and still undecided is more
    of a problem than one raised yesterday, and a window would hide exactly the
    ones that have been sitting longest.
    """
    # Order matters: the two stale expressions come before the date bound.
    args: list[object] = [
        as_of.isoformat(), STALE_DAYS,   # stale_n
        as_of.isoformat(), STALE_DAYS,   # stale_v
        as_of.isoformat(),               # return_date <= ?
    ]
    clause = _region_clause(region_id, args)
    row = conn.execute(
        f"""SELECT COUNT(*) AS n,
              COALESCE(SUM(r.credit_note_value_inr), 0) AS v,
              MIN(r.return_date) AS oldest,
              COALESCE(SUM(julianday(?) - julianday(r.return_date) > ?), 0)
                AS stale_n,
              COALESCE(SUM(CASE WHEN julianday(?) - julianday(r.return_date) > ?
                           THEN r.credit_note_value_inr END), 0) AS stale_v
            FROM returns_credit_notes r
            JOIN outlets ot ON ot.outlet_id = r.outlet_id
           WHERE r.status IN {_UNDECIDED_IN}
             AND r.return_date <= ? {clause}
             AND {outlet_filter()}""",
        args,
    ).fetchone()

    oldest = date.fromisoformat(row["oldest"][:10]) if row["oldest"] else None
    return PendingQueue(
        notes_n=row["n"],
        value_inr=row["v"],
        oldest_date=oldest,
        oldest_days=(as_of - oldest).days if oldest else None,
        stale_n=row["stale_n"],
        stale_inr=row["stale_v"],
    )


def pending_to_work(
    conn: sqlite3.Connection,
    as_of: date,
    region_id: int | None = None,
    limit: int = 5,
) -> list[dict]:
    """The undecided notes worth the most, each carrying how long it has waited.

    Ordered by value, not by age — the two disagree completely here. The oldest
    notes are worth tens of rupees while the largest have waited months, so an
    age-sorted list reads like a work queue and is not one. Age stays visible on
    every row, and how much of the pile has gone stale is on the queue summary.
    """
    args: list[object] = [as_of.isoformat()]
    clause = _region_clause(region_id, args)
    args.append(limit)
    rows = conn.execute(
        f"""SELECT r.credit_note_number AS ref, ot.outlet_name AS outlet,
                   r.return_date, r.credit_note_value_inr AS value_inr
              FROM returns_credit_notes r
              JOIN outlets ot ON ot.outlet_id = r.outlet_id
             WHERE r.status IN {_UNDECIDED_IN}
               AND r.return_date <= ? {clause}
               AND {outlet_filter()}
             ORDER BY r.credit_note_value_inr DESC LIMIT ?""",
        args,
    ).fetchall()
    return [
        {
            **dict(r),
            "days_waiting": (as_of - date.fromisoformat(r["return_date"][:10])).days,
        }
        for r in rows
    ]
