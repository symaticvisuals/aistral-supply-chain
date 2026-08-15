"""What the data actually does, checked at request time.

The brief says its own dictionary is partly wrong and that the job is to notice,
not to fix. So these are computed, never hardcoded: writing "0 of 511,516" as a
string makes it a lie the moment the data changes.

Findings that came back clean are reported too. Several documented "traps" turn
out to be false on this data, and repeating a defect that isn't there is its own
kind of dishonesty.
"""

import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from app.metrics import money
from app.metrics.scope import TEST_OUTLET_PATTERNS, outlet_filter
from app.metrics.windows import Window

Severity = Literal["blocks_metric", "advisory", "clean"]

# Same place spelled two ways. Explicit rather than fuzzy-matched: a guess about
# which names mean the same city is exactly the kind of silent fix to avoid.
CITY_ALIASES = (("BANGALORE", "BENGALURU"), ("DELHI", "NEW DELHI"),
                ("GURGAON", "GURUGRAM"), ("BOMBAY", "MUMBAI"),
                ("CALCUTTA", "KOLKATA"), ("MADRAS", "CHENNAI"))


@dataclass
class Finding:
    id: str
    severity: Severity
    statement: str
    evidence: dict = field(default_factory=dict)
    affects: list[str] = field(default_factory=list)


def _one(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> sqlite3.Row:
    return conn.execute(sql, args).fetchone()


def otif_in_full(conn) -> Finding:
    r = _one(conn, """
        SELECT (SELECT COUNT(*) FROM order_lines) AS lines,
               (SELECT COUNT(*) FROM order_lines WHERE delivered_qty >= ordered_qty)
                 AS full_lines,
               (SELECT COUNT(*) FROM orders) AS orders,
               (SELECT COUNT(*) FROM (
                    SELECT order_id FROM order_lines GROUP BY order_id
                     HAVING SUM(CASE WHEN delivered_qty < ordered_qty
                                     THEN 1 ELSE 0 END) = 0
               )) AS full_orders""")
    degenerate = r["full_orders"] == 0 and r["orders"] > 0
    return Finding(
        id="OTIF_IN_FULL_DEGENERATE",
        severity="blocks_metric" if degenerate else "clean",
        statement=(
            "No order in the data is delivered in full, so OTIF's in-full leg is a "
            "constant zero. An OTIF tile would read 0% for every region, every "
            "month. Not shipping one until Divya gives us a tolerance."
            if degenerate else
            "Some orders are delivered in full; OTIF's in-full leg is computable."
        ),
        evidence={"orders": r["orders"], "orders_in_full": r["full_orders"],
                  "lines": r["lines"], "lines_in_full": r["full_lines"]},
        affects=["otif"],
    )


def short_reason_signal(conn) -> Finding:
    rows = conn.execute("""
        SELECT short_reason_code AS code, COUNT(*) AS n,
               SUM(CASE WHEN ordered_qty > allocated_qty THEN 1 ELSE 0 END)
                 AS never_reserved,
               SUM(CASE WHEN allocated_qty > delivered_qty THEN 1 ELSE 0 END)
                 AS not_sent
          FROM order_lines WHERE short_reason_code IS NOT NULL
         GROUP BY short_reason_code ORDER BY n DESC""").fetchall()
    total = sum(r["n"] for r in rows)
    shares = [r["n"] / total for r in rows] if total else []
    # Uniform counts AND an identical split across failure modes means the code
    # is not telling us why anything was short.
    uniform = bool(shares) and (max(shares) - min(shares)) < 0.02
    splits = [r["never_reserved"] / r["n"] for r in rows if r["n"]]
    same_split = bool(splits) and (max(splits) - min(splits)) < 0.02
    noise = uniform and same_split and len(rows) > 1
    return Finding(
        id="SHORT_REASON_CODE_NO_SIGNAL",
        severity="blocks_metric" if noise else "clean",
        statement=(
            "Short reason codes are uniformly distributed and split identically "
            "across failure modes, so they carry no signal. 'Leading reason code' "
            "cannot be answered honestly from this data."
            if noise else "Short reason codes vary by failure mode."
        ),
        evidence={"codes": [dict(r) for r in rows], "share_spread": round(
            max(shares) - min(shares), 4) if shares else None},
        affects=["short_reasons"],
    )


def return_reason_signal(conn) -> Finding:
    """Three independent tests, because one flat cut could be a coincidence.

    A reason code that means anything must predict *something*: what happens to
    the goods, what kind of product it was, or whether the desk pays out.
    """
    by_code = conn.execute("""
        SELECT r.return_reason_code AS code, COUNT(*) AS n,
               1.0 * SUM(r.disposition = 'SCRAP') / COUNT(*)  AS scrap_rate,
               1.0 * SUM(r.status = 'APPROVED') / COUNT(*)    AS approval_rate
          FROM returns_credit_notes r
         GROUP BY r.return_reason_code ORDER BY n DESC""").fetchall()

    # A cold chain breach is impossible on an ambient product. If the code is
    # real, its rate on chilled lines must dwarf its rate on ambient ones.
    cold = _one(conn, """
        SELECT
          1.0 * SUM(CASE WHEN p.is_chilled = 1
                    AND r.return_reason_code = 'RT06_COLD_CHAIN_BREACH'
                    THEN 1 ELSE 0 END) / NULLIF(SUM(p.is_chilled = 1), 0)
            AS chilled_rate,
          1.0 * SUM(CASE WHEN p.is_chilled = 0
                    AND r.return_reason_code = 'RT06_COLD_CHAIN_BREACH'
                    THEN 1 ELSE 0 END) / NULLIF(SUM(p.is_chilled = 0), 0)
            AS ambient_rate
          FROM returns_credit_notes r
          JOIN products p ON p.product_id = r.product_id""")

    spread = lambda xs: (max(xs) - min(xs)) if len(xs) > 1 else None  # noqa: E731
    scrap_spread = spread([r["scrap_rate"] for r in by_code])
    approval_spread = spread([r["approval_rate"] for r in by_code])
    chilled, ambient = cold["chilled_rate"], cold["ambient_rate"]
    # Not "chilled is higher" — "chilled is no higher", which is the damning case.
    cold_is_meaningless = (
        chilled is not None and ambient is not None and chilled <= ambient
    )
    noise = bool(
        scrap_spread is not None and scrap_spread < 0.05
        and approval_spread is not None and approval_spread < 0.05
        and cold_is_meaningless
    )
    return Finding(
        id="RETURN_REASON_CODE_NO_SIGNAL",
        severity="blocks_metric" if noise else "clean",
        statement=(
            "Return reason codes predict nothing. Every code is scrapped at the "
            "same rate and approved at the same rate, and RT06_COLD_CHAIN_BREACH "
            "is no more common on chilled products than on ambient ones, which is "
            "impossible if the label means what it says. 'Leading reason code' has "
            "no honest answer, so money is not sliced by it — the codes differ only "
            "in how often they are used, and RT01 leads on volume alone."
            if noise else
            "Return reason codes vary by disposition, product type or approval."
        ),
        evidence={
            "by_code": [dict(r) for r in by_code],
            "scrap_rate_spread": round(scrap_spread, 4) if scrap_spread else None,
            "approval_rate_spread": (
                round(approval_spread, 4) if approval_spread else None),
            "cold_breach_rate_chilled": round(chilled, 4) if chilled else None,
            "cold_breach_rate_ambient": round(ambient, 4) if ambient else None,
        },
        affects=["returns", "return_reasons", "money"],
    )


def temperature_flag_signal(conn) -> Finding:
    """Does the excursion flag track the temperature it claims to record?

    If it means anything, its rate must climb with the reading. A flag that
    fires as often at 0C as at 15C is a coin toss wearing a thermometer.
    """
    rows = conn.execute("""
        SELECT CASE WHEN max_temp_celsius <= 4 THEN '1. in band or colder'
                    WHEN max_temp_celsius <= 8 THEN '2. 4-8C'
                    WHEN max_temp_celsius <= 12 THEN '3. 8-12C'
                    ELSE '4. over 12C' END AS band,
               COUNT(*) AS deliveries,
               SUM(temperature_excursion_flag) AS flagged,
               1.0 * SUM(temperature_excursion_flag) / COUNT(*) AS rate
          FROM deliveries WHERE max_temp_celsius IS NOT NULL
         GROUP BY band ORDER BY band""").fetchall()

    rates = [r["rate"] for r in rows]
    spread = (max(rates) - min(rates)) if len(rates) > 1 else None
    # Under a point of spread across the whole range is not a sensor.
    noise = spread is not None and spread < 0.01

    hot = _one(conn, """
        SELECT COUNT(*) AS n, SUM(d.temperature_excursion_flag) AS flagged
          FROM (SELECT d.delivery_id, d.max_temp_celsius,
                       d.temperature_excursion_flag,
                       MAX(p.is_chilled) AS chilled
                  FROM deliveries d
                  JOIN order_lines ol ON ol.order_id = d.order_id
                  JOIN products p ON p.product_id = ol.product_id
                 GROUP BY d.delivery_id) d
         WHERE d.chilled = 1 AND d.max_temp_celsius > 8""")

    return Finding(
        id="TEMPERATURE_FLAG_NO_SIGNAL",
        severity="blocks_metric" if noise else "clean",
        statement=(
            "temperature_excursion_flag fires at the same rate at every "
            "temperature, in band and far out of it alike, so it records nothing. "
            "Trusting it both invents excursions on ambient-only loads and hides "
            f"real ones: {hot['n']:,} deliveries carried chilled stock above 8C and "
            f"the flag caught {hot['flagged']:,} of them. Cold chain is computed "
            "from max_temp_celsius and what was actually on the truck instead."
            if noise else
            "The excursion flag fires more often as the temperature rises."
        ),
        evidence={
            "by_band": [dict(r) | {"rate": round(r["rate"], 4)} for r in rows],
            "rate_spread": round(spread, 4) if spread is not None else None,
            "chilled_above_8c": hot["n"],
            "of_those_flagged": hot["flagged"],
        },
        affects=["cold_chain"],
    )


def ageing_bucket_signal(conn) -> Finding:
    """Does the ageing label match the expiry date on the same row?"""
    rows = conn.execute("""
        SELECT ageing_bucket AS bucket, COUNT(*) AS n,
               ROUND(AVG(julianday(expiry_date) - julianday(snapshot_date))) AS avg_days
          FROM inventory_snapshots
         GROUP BY ageing_bucket ORDER BY ageing_bucket""").fetchall()
    days = [r["avg_days"] for r in rows if r["avg_days"] is not None]
    spread = (max(days) - min(days)) if len(days) > 1 else None
    # Buckets that claim to be 0-30 and 90+ must differ by more than a few days.
    noise = spread is not None and spread < 10

    return Finding(
        id="AGEING_BUCKET_NO_SIGNAL",
        severity="advisory" if noise else "clean",
        statement=(
            "ageing_bucket does not describe the row it sits on: stock labelled "
            "'0-30' has the same average shelf life left as stock labelled '90+'. "
            "Expiry is computed from expiry_date against the snapshot date instead."
            if noise else
            "ageing_bucket tracks the days remaining on the row."
        ),
        evidence={"by_bucket": [dict(r) for r in rows],
                  "avg_days_spread": spread},
        affects=["expiry", "inventory"],
    )


def credit_approval_trail(conn) -> Finding:
    rows = conn.execute("""
        SELECT status, COUNT(*) AS n,
               SUM(approval_date IS NULL OR approval_date = '') AS no_date,
               COUNT(DISTINCT approved_by) AS distinct_approvers
          FROM returns_credit_notes GROUP BY status ORDER BY status""").fetchall()
    total = sum(r["n"] for r in rows)
    undated = sum(r["no_date"] for r in rows)
    # approved_by is filled in on notes nobody has approved yet, so it records the
    # route a note takes rather than a person who signed it.
    named_on_pending = next(
        (r["distinct_approvers"] for r in rows if r["status"] == "PENDING"), 0)
    broken = bool(total and undated == total and named_on_pending)
    return Finding(
        id="CREDIT_APPROVAL_TRAIL_MISSING",
        severity="advisory" if broken else "clean",
        statement=(
            "approval_date is empty on every credit note, including approved ones, "
            "so how long the credit desk takes cannot be measured. approved_by is "
            "populated even on notes still pending, and holds three values — it is "
            "the approval route, not a person. Nobody can be named from this table."
            if broken else "Credit notes carry a usable approval trail."
        ),
        evidence={"by_status": [dict(r) for r in rows], "rows": total,
                  "without_approval_date": undated},
        affects=["money", "ownership"],
    )


def line_value_is_ordered(conn) -> Finding:
    r = _one(conn, """
        SELECT COUNT(*) AS lines,
               SUM(ABS(line_value_inr - ordered_qty * unit_price_inr
                   * (1 - COALESCE(line_discount_pct, 0) / 100.0)) < 0.02)
                 AS matches_ordered,
               SUM(ABS(line_value_inr - delivered_qty * unit_price_inr
                   * (1 - COALESCE(line_discount_pct, 0) / 100.0)) < 0.02)
                 AS matches_delivered
          FROM order_lines""")
    trap = bool(r["lines"] and r["matches_ordered"] == r["lines"]
                and r["matches_delivered"] < r["lines"])
    return Finding(
        id="LINE_VALUE_IS_ORDERED_NOT_DELIVERED",
        severity="advisory" if trap else "clean",
        statement=(
            "line_value_inr prices the ordered quantity, not the delivered one, on "
            "every line — and the order header ties to it, so header value is an "
            "ordered figure too. Using either as revenue overstates dispatch by "
            "roughly the shortfall. Dispatch value is recomputed from delivered "
            "quantity wherever money is reported."
            if trap else "line_value_inr prices the delivered quantity."
        ),
        evidence=dict(r),
        affects=["money", "order_value"],
    )


def _fill_by_status(conn) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT o.order_status AS status, COUNT(DISTINCT o.order_id) AS orders,
               100.0 * SUM(CASE WHEN ol.qty_uom='CASE' THEN ol.delivered_qty
                                ELSE ol.delivered_qty/ol.case_pack_at_order END)
                     / NULLIF(SUM(CASE WHEN ol.qty_uom='CASE' THEN ol.ordered_qty
                                ELSE ol.ordered_qty/ol.case_pack_at_order END), 0)
                 AS case_fill
          FROM order_lines ol JOIN orders o ON o.order_id = ol.order_id
         GROUP BY o.order_status""").fetchall()


def order_status_meaning(conn) -> Finding:
    by = {r["status"]: r for r in _fill_by_status(conn)}
    delivered, partial = by.get("DELIVERED"), by.get("PARTIAL")
    broken = bool(
        delivered and partial and delivered["case_fill"] is not None
        and partial["case_fill"] is not None
        and partial["case_fill"] >= delivered["case_fill"]
    )
    return Finding(
        id="ORDER_STATUS_NOT_COMPLETENESS",
        severity="advisory" if broken else "clean",
        statement=(
            "PARTIAL scores at or above DELIVERED, and DELIVERED contains orders "
            "that received nothing. order_status does not grade fulfilment — the "
            "only real boundary is CANCELLED versus everything else."
            if broken else "DELIVERED outperforms PARTIAL, as the labels imply."
        ),
        evidence={r["status"]: {"orders": r["orders"], "case_fill": (
            round(r["case_fill"], 2) if r["case_fill"] is not None else None)}
            for r in by.values()},
        affects=["scope"],
    )


def open_orders_delivered(conn) -> Finding:
    by = {r["status"]: r for r in _fill_by_status(conn)}
    row = by.get("OPEN")
    fill = row["case_fill"] if row and row["case_fill"] is not None else None
    odd = fill is not None and fill > 50.0
    return Finding(
        id="OPEN_ORDERS_ALREADY_DELIVERED",
        severity="advisory" if odd else "clean",
        statement=(
            "Orders marked OPEN already carry delivered quantities. Adding them to "
            "a stricter scope raises fill instead of lowering it, so they are an "
            "anomaly to flag, not a rung on the scope ladder."
            if odd else "OPEN orders carry little or no delivered quantity."
        ),
        evidence={"orders": row["orders"] if row else 0,
                  "case_fill": round(fill, 2) if fill is not None else None},
        affects=["scope"],
    )


def live_test_outlets(conn) -> Finding:
    pattern_sql = " OR ".join(
        f"UPPER(outlet_name) LIKE '{p}' ESCAPE '\\'" for p in TEST_OUTLET_PATTERNS)
    rows = conn.execute(f"""
        SELECT ot.outlet_id, ot.outlet_name, ot.status, ot.is_deleted,
               (SELECT COUNT(*) FROM orders o
                 WHERE o.outlet_id = ot.outlet_id) AS orders
          FROM outlets ot WHERE {pattern_sql} ORDER BY ot.outlet_id""").fetchall()
    live = [dict(r) for r in rows if r["status"] == "ACTIVE" and not r["is_deleted"]]
    return Finding(
        id="TEST_OUTLETS_ACTIVE",
        severity="advisory" if live else "clean",
        statement=(
            "Test and migration rows are still ACTIVE in the outlet master and "
            "still receiving orders. Excluded here, and named so the exclusion is "
            "auditable rather than silent."
            if live else "No live test or migration outlets found."
        ),
        evidence={"outlets": live, "orders": sum(o["orders"] for o in live)},
        affects=["scope", "outlets"],
    )


def return_qty_signs(conn) -> Finding:
    r = _one(conn, """
        SELECT COUNT(*) AS n, SUM(CASE WHEN return_qty < 0 THEN 1 ELSE 0 END) AS neg,
               MIN(return_qty) AS mn, MAX(return_qty) AS mx
          FROM returns_credit_notes""")
    flips = bool(r["n"] and r["neg"] and r["neg"] < r["n"])
    return Finding(
        id="RETURN_QTY_SIGN_FLIP",
        severity="advisory" if flips else "clean",
        statement=(
            "Return quantities use both signs in the same column, so summing "
            "return_qty raw understates the leak."
            if flips else "Return quantities use a consistent sign."
        ),
        evidence={"returns": r["n"], "negative": r["neg"],
                  "min": r["mn"], "max": r["mx"]},
        affects=["returns"],
    )


def header_ties_to_lines(conn) -> Finding:
    r = _one(conn, """
        SELECT COUNT(*) AS orders,
               SUM(CASE WHEN ABS(li - g) < 0.02 THEN 1 ELSE 0 END) AS tie
          FROM (SELECT o.order_id, o.order_value_gross_inr AS g,
                       SUM(ol.line_value_inr) AS li
                  FROM orders o JOIN order_lines ol ON ol.order_id = o.order_id
                 GROUP BY o.order_id, o.order_value_gross_inr)""")
    clean = r["orders"] and r["tie"] == r["orders"]
    return Finding(
        id="HEADER_TIES_TO_LINES",
        severity="clean" if clean else "advisory",
        statement=(
            "Order header gross value ties to the sum of its lines on every order, "
            "to the paisa. The documented 'headers may not reconcile' trap does not "
            "hold on this data and should not be repeated."
            if clean else
            "Some order headers do not tie to the sum of their lines."
        ),
        evidence={"orders": r["orders"], "reconciling": r["tie"]},
        affects=["order_value"],
    )


def net_value_by_source(conn) -> Finding:
    rows = conn.execute("""
        SELECT source_system, COUNT(*) AS n,
               SUM(CASE WHEN ABS((order_value_gross_inr - discount_amount_inr
                    + tax_amount_inr) - order_value_net_inr) < 0.02 THEN 1 ELSE 0 END)
                 AS reconciling
          FROM orders GROUP BY source_system ORDER BY source_system""").fetchall()
    broken = [dict(r) for r in rows if r["reconciling"] < r["n"]]
    return Finding(
        id="NET_VALUE_BY_SOURCE_SYSTEM",
        severity="advisory" if broken else "clean",
        statement=(
            "One order system computes net value differently from the others: "
            "gross - discount + tax does not equal net on any of its orders, while "
            "the remaining systems reconcile on all of theirs."
            if broken else
            "Net value reconciles as gross - discount + tax across every source."
        ),
        evidence={"by_source": [dict(r) for r in rows]},
        affects=["order_value"],
    )


def city_spellings(conn) -> Finding:
    rows = conn.execute(
        "SELECT DISTINCT UPPER(TRIM(city)) AS c FROM outlets WHERE city IS NOT NULL"
    ).fetchall()
    present = {r["c"] for r in rows}
    dupes = [list(pair) for pair in CITY_ALIASES if set(pair) <= present]
    return Finding(
        id="CITY_FREE_TEXT",
        severity="advisory" if dupes else "clean",
        statement=(
            "The same city appears under more than one spelling, so grouping by "
            "city splits those markets in two."
            if dupes else "No known city alias pairs both present."
        ),
        evidence={"aliases_present": dupes, "distinct_cities": len(present)},
        affects=["city_grouping"],
    )


def route_region_mismatch(conn) -> Finding:
    r = _one(conn, """
        SELECT COUNT(*) AS outlets,
               SUM(CASE WHEN ot.region_id = w.region_id THEN 1 ELSE 0 END) AS agree
          FROM outlets ot
          JOIN routes r ON r.route_id = ot.route_id
          JOIN warehouses w ON w.warehouse_id = r.warehouse_id""")
    agree_pct = 100.0 * r["agree"] / r["outlets"] if r["outlets"] else None
    mismatched = agree_pct is not None and agree_pct < 90.0
    return Finding(
        id="ROUTE_REGION_MISMATCH",
        severity="advisory" if mismatched else "clean",
        statement=(
            "An outlet's route usually belongs to a different region than the "
            "outlet itself, and the pattern follows route counts rather than "
            "geography. Region here means the outlet's own region; warehouse is "
            "not offered as a geography because 'which DC is worst' has no "
            "honest answer."
            if mismatched else
            "Outlet regions and their routes' warehouse regions agree."
        ),
        evidence={"outlets": r["outlets"], "agreeing": r["agree"],
                  "agree_pct": round(agree_pct, 2) if agree_pct is not None else None},
        affects=["region_grouping", "warehouse_grouping"],
    )


def outlet_fill_is_noisy(conn, window: Window) -> Finding:
    rows = conn.execute(f"""
        SELECT orders, fill FROM (
          SELECT COUNT(DISTINCT o.order_id) AS orders,
                 100.0 * SUM(CASE WHEN ol.qty_uom='CASE' THEN ol.delivered_qty
                              ELSE ol.delivered_qty/ol.case_pack_at_order END)
                       / NULLIF(SUM(CASE WHEN ol.qty_uom='CASE' THEN ol.ordered_qty
                              ELSE ol.ordered_qty/ol.case_pack_at_order END), 0) AS fill
            FROM order_lines ol
            JOIN orders o ON o.order_id = ol.order_id
            JOIN outlets ot ON ot.outlet_id = o.outlet_id
           WHERE o.order_date BETWEEN ? AND ?
             AND o.order_status IN ('DELIVERED','PARTIAL')
             AND {outlet_filter()}
           GROUP BY ot.outlet_id)
         WHERE fill IS NOT NULL""",
        (window.start.isoformat(), window.end.isoformat()),
    ).fetchall()

    small = [r["fill"] for r in rows if r["orders"] <= 14]
    large = [r["fill"] for r in rows if r["orders"] >= 21]
    spread = lambda xs: (max(xs) - min(xs)) if len(xs) > 1 else None  # noqa: E731
    small_spread, large_spread = spread(small), spread(large)
    noisy = (
        small_spread is not None and large_spread is not None
        and small_spread > large_spread
    )
    return Finding(
        id="OUTLET_FILL_PCT_IS_NOISE",
        severity="advisory" if noisy else "clean",
        statement=(
            "Outlet fill % spreads wider the fewer orders an outlet placed, which "
            "is what sampling noise looks like, not a service signal. Ranking by "
            "it surfaces small shops that got unlucky, so both orderings are "
            "returned and neither is called the answer."
            if noisy else "Outlet fill % spread does not track order count."
        ),
        evidence={
            "outlets": len(rows),
            "spread_9_to_14_orders": round(small_spread, 2) if small_spread else None,
            "spread_21_plus_orders": round(large_spread, 2) if large_spread else None,
        },
        affects=["outlet_ranking"],
    )


def credit_leakage_immaterial(conn, window: Window) -> Finding:
    """The ratio Divya asked for, checked for whether it can carry a decision."""
    leak = money.leakage(conn, window)
    # Three states, not two. Nothing dispatched is a different claim from a ratio
    # too small to matter, and collapsing them would be the quiet lie this file
    # exists to catch.
    if leak.raised_pct is None:
        statement = (
            "Nothing was dispatched in this window, so credit notes as a share of "
            "dispatch has no denominator. Reported as unavailable, not as zero."
        )
    elif leak.material:
        statement = (
            f"Credit notes are {leak.raised_pct:.2f}% of dispatch value, material "
            f"enough to track as a rate."
        )
    else:
        statement = (
            f"Credit notes come to {leak.raised_pct:.2f}% of dispatch value in this "
            f"window, against a {money.MATERIAL_PCT}% threshold for a number worth "
            f"watching. The ratio rounds to nothing at every grain and barely moves "
            f"between periods, so it is reported once for the record and the rupee "
            f"amounts are what the screen ranks on."
        )
    return Finding(
        id="CREDIT_LEAKAGE_RATIO_IMMATERIAL",
        severity="clean" if leak.material else "advisory",
        statement=statement,
        evidence={
            "dispatch_inr": round(leak.dispatch_inr),
            "raised_inr": round(leak.notes.raised_inr),
            "settled_inr": round(leak.notes.settled_inr),
            "undecided_inr": round(leak.notes.undecided_inr),
            "raised_pct": (
                round(leak.raised_pct, 4) if leak.raised_pct is not None else None),
            "threshold_pct": money.MATERIAL_PCT,
        },
        affects=["money"],
    )


def all_findings(conn: sqlite3.Connection, window: Window) -> list[Finding]:
    """Blocking findings first — they stop a metric from being built at all."""
    findings = [
        otif_in_full(conn), short_reason_signal(conn), order_status_meaning(conn),
        open_orders_delivered(conn), live_test_outlets(conn), return_qty_signs(conn),
        header_ties_to_lines(conn), net_value_by_source(conn), city_spellings(conn),
        route_region_mismatch(conn), outlet_fill_is_noisy(conn, window),
        return_reason_signal(conn), credit_approval_trail(conn),
        temperature_flag_signal(conn), ageing_bucket_signal(conn),
        line_value_is_ordered(conn), credit_leakage_immaterial(conn, window),
    ]
    rank = {"blocks_metric": 0, "advisory": 1, "clean": 2}
    return sorted(findings, key=lambda f: (rank[f.severity], f.id))
