"""Stock that will not sell before it expires.

Everything else in this service is a post-mortem: what broke yesterday. This is
the one thing that says what is about to break, which makes it the only place
Divya can act before the money is gone.

It closes a loop the returns data opens. RT01_NEAR_EXPIRY is the largest credit
note reason by value, so near-expiry stock in a DC is the upstream cause of the
biggest thing the credit desk pays out on. Catching it on the rack costs a
transfer or a promotion; catching it at the shop costs a credit note.

Two readings, and they are nested rather than opposed:

    near expiry        expiry is within NEAR_DAYS
    cannot sell        days_of_cover exceeds the days left

The second is the sharp one — it is arithmetic, not a worry. The depot holds
more than it can move in the time remaining. Note the ceiling: days_of_cover
tops out at 40 in this data, so the test can never flag a slow mover with three
months left. That bound is reported rather than hidden.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

# "Near" is a judgement, not a fact. One place to change it.
NEAR_DAYS = 30

# Snapshots land weekly. Anything older than this and the stock position on
# screen is not the one in the warehouse.
STALE_SNAPSHOT_DAYS = 8

# Value at list price. list_price_inr is per each — verified against
# order_lines.unit_price_inr, which matches it exactly on EACH lines and comes
# to case_pack times it on CASE lines.
_VALUE = "i.on_hand_cases * p.case_pack * p.list_price_inr"
_DAYS_LEFT = "julianday(i.expiry_date) - julianday(i.snapshot_date)"


@dataclass(frozen=True)
class StockLine:
    warehouse: str
    product: str
    sku: str
    batch: str
    on_hand_cases: int
    days_left: int
    days_of_cover: float
    value_inr: float
    expiry_date: str
    cannot_sell: bool


@dataclass(frozen=True)
class AtRisk:
    snapshot_date: date | None
    snapshot_age_days: int | None
    is_stale: bool
    near_lines: int
    near_cases: int
    near_value_inr: float
    doomed_lines: int
    doomed_cases: int
    doomed_value_inr: float
    lines: list[StockLine]


def latest_snapshot(conn: sqlite3.Connection, on_or_before: date) -> date | None:
    """The stock position as it was known on that morning, never a later one."""
    row = conn.execute(
        "SELECT MAX(snapshot_date) AS d FROM inventory_snapshots"
        " WHERE snapshot_date <= ?",
        (on_or_before.isoformat(),),
    ).fetchone()
    return date.fromisoformat(row["d"][:10]) if row and row["d"] else None


def at_risk(
    conn: sqlite3.Connection,
    as_of: date,
    region_id: int | None = None,
    limit: int = 10,
) -> AtRisk:
    """What is on the rack that should not still be there.

    `region_id` filters on the *warehouse's* region, not the outlet's. This is
    physical stock sitting in a DC, so the DC's own geography is the only one
    that means anything here — which is a different question from the region
    filter everywhere else in this service, where region means the shop's.
    """
    snapshot = latest_snapshot(conn, as_of)
    if snapshot is None:
        return AtRisk(None, None, True, 0, 0, 0.0, 0, 0, 0.0, [])

    args: list[object] = [snapshot.isoformat()]
    clause = ""
    if region_id is not None:
        clause = "AND w.region_id = ?"
        args.append(region_id)

    rows = conn.execute(
        f"""SELECT w.warehouse_code AS warehouse, p.product_name AS product,
                   p.sku_code AS sku, i.batch_id AS batch,
                   i.on_hand_cases, i.days_of_cover, i.expiry_date,
                   CAST({_DAYS_LEFT} AS INTEGER) AS days_left,
                   ROUND({_VALUE}) AS value_inr
              FROM inventory_snapshots i
              JOIN products p   ON p.product_id = i.product_id
              JOIN warehouses w ON w.warehouse_id = i.warehouse_id
             WHERE i.snapshot_date = ? {clause}
               AND i.on_hand_cases > 0
               AND ({_DAYS_LEFT} <= {NEAR_DAYS}
                    OR i.days_of_cover > {_DAYS_LEFT})
             ORDER BY value_inr DESC""",
        args,
    ).fetchall()

    lines = [
        StockLine(
            warehouse=r["warehouse"], product=r["product"], sku=r["sku"],
            batch=r["batch"], on_hand_cases=r["on_hand_cases"],
            days_left=r["days_left"], days_of_cover=r["days_of_cover"],
            value_inr=r["value_inr"], expiry_date=r["expiry_date"][:10],
            cannot_sell=r["days_of_cover"] > r["days_left"],
        )
        for r in rows
    ]
    near = [line for line in lines if line.days_left <= NEAR_DAYS]
    doomed = [line for line in lines if line.cannot_sell]
    age = (as_of - snapshot).days

    return AtRisk(
        snapshot_date=snapshot,
        snapshot_age_days=age,
        is_stale=age > STALE_SNAPSHOT_DAYS,
        near_lines=len(near),
        near_cases=sum(line.on_hand_cases for line in near),
        near_value_inr=sum(line.value_inr for line in near),
        doomed_lines=len(doomed),
        doomed_cases=sum(line.on_hand_cases for line in doomed),
        doomed_value_inr=sum(line.value_inr for line in doomed),
        # Ranked by value, and the ones that cannot sell through come first —
        # those are arithmetic rather than a worry.
        lines=sorted(lines, key=lambda s: (not s.cannot_sell, -s.value_inr))[:limit],
    )
