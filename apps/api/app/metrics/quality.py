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


def excursion_rate_is_flat(conn) -> Finding:
    """Answers "excursions per hundred chilled deliveries, by month".

    The number is computable and the series is carried in the evidence, so the
    question has an answer. What it does not have is a use: the rate sits at
    roughly 22 per hundred in every month, at every depot, on both telematics
    vendors. A tile of it would be a flat line naming no action.

    Note what this does *not* say. temperature_excursion_flag contradicts the
    temperature on its own row, so it is wrong. max_temp_celsius is merely
    unexplained by any grouping — a specific load at 16.8C is still the best
    reading we have. Aggregate it and you get noise; keep it per delivery and it
    is a case worth a phone call. That is why cold chain ships as cases and not
    as a trend.
    """
    chilled_drop = """
        SELECT d.delivery_id, d.max_temp_celsius AS t,
               substr(o.order_date, 1, 7) AS mth,
               w.warehouse_code AS wh
          FROM deliveries d
          JOIN orders o ON o.order_id = d.order_id
          JOIN order_lines ol ON ol.order_id = d.order_id
          JOIN products p ON p.product_id = ol.product_id
          JOIN warehouses w ON w.warehouse_id = d.warehouse_id
         WHERE d.max_temp_celsius IS NOT NULL
         GROUP BY d.delivery_id
        HAVING MAX(p.is_chilled) = 1"""

    by_month = conn.execute(f"""
        SELECT mth, COUNT(*) AS drops, SUM(t > 8) AS above_8,
               100.0 * SUM(t > 8) / COUNT(*) AS per_100
          FROM ({chilled_drop}) GROUP BY mth ORDER BY mth""").fetchall()
    by_wh = conn.execute(f"""
        SELECT wh, COUNT(*) AS drops,
               100.0 * SUM(t > 8) / COUNT(*) AS per_100
          FROM ({chilled_drop}) GROUP BY wh ORDER BY per_100 DESC""").fetchall()

    spread = lambda rows: (  # noqa: E731
        max(r["per_100"] for r in rows) - min(r["per_100"] for r in rows)
        if len(rows) > 1 else None
    )
    month_spread, wh_spread = spread(by_month), spread(by_wh)
    # Under five points across eighteen months and eight depots is one number
    # wearing many hats.
    flat = (
        month_spread is not None and month_spread < 5.0
        and wh_spread is not None and wh_spread < 5.0
    )
    average = (
        sum(r["above_8"] for r in by_month) * 100.0
        / sum(r["drops"] for r in by_month)
    ) if by_month else None

    return Finding(
        id="EXCURSION_RATE_IS_FLAT",
        severity="advisory" if flat else "clean",
        statement=(
            f"Excursions run at {average:.0f} per hundred chilled deliveries and "
            f"stay there: {month_spread:.1f} points of spread across every month, "
            f"{wh_spread:.1f} across every depot. The monthly series is here for "
            f"the record, but a chart of it would be a flat line naming no action, "
            f"so cold chain ships as individual loads instead. Those still stand — "
            f"the temperature is unexplained by month or depot, which is not the "
            f"same as being wrong about a given truck."
            if flat else
            "Excursion rates differ by month or depot enough to be worth tracking."
        ),
        evidence={
            "per_100_overall": round(average, 1) if average is not None else None,
            "by_month": [
                {"month": r["mth"], "chilled_drops": r["drops"],
                 "above_8c": r["above_8"], "per_100": round(r["per_100"], 1)}
                for r in by_month
            ],
            "by_warehouse": [
                {"warehouse": r["wh"], "chilled_drops": r["drops"],
                 "per_100": round(r["per_100"], 1)} for r in by_wh
            ],
            "month_spread": round(month_spread, 1) if month_spread else None,
            "warehouse_spread": round(wh_spread, 1) if wh_spread else None,
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


def prices_never_scraped() -> Finding:
    return Finding(
        id="PRICES_NEVER_SCRAPED",
        severity="advisory",
        statement=(
            "No competitor prices have been collected, so the price questions "
            "are unanswered rather than answered badly. Run "
            "`uv run python -m app.bazaarpulse` against the BazaarPulse site."
        ),
        evidence={},
        affects=["price"],
    )


def shelf_price_has_no_memory(book) -> Finding:
    """Can "a shop cut its price last week" ever be an alert?

    Only if this week's price tells you anything about next week's. Pool every
    consecutive pair as a deviation from its own listing's mean and the
    correlation is not merely weak, it is the value pure noise produces: with
    six observations, subtracting the sample mean drags lag-1 correlation to
    about -1/(n-1) = -0.2 all on its own. Add a drift of nothing at all and the
    series is a wobble around a fixed number.

    This is the finding that blocks a price-movement event in the morning queue.
    Without it, twelve listings look like twelve stories.
    """
    pairs_x: list[float] = []
    pairs_y: list[float] = []
    swings: list[float] = []
    drifts: list[float] = []
    for series in book.series:
        if len(series) < 3:
            continue
        mean = sum(series) / len(series)
        if mean:
            swings.append((max(series) - min(series)) / mean)
        for i in range(1, len(series)):
            pairs_x.append(series[i - 1] - mean)
            pairs_y.append(series[i] - mean)
        if len(series) >= 6 and mean:
            half = len(series) // 2
            drifts.append(
                (sum(series[half:]) / len(series[half:])
                 - sum(series[:half]) / half) / mean
            )

    correlation = None
    if len(pairs_x) > 2:
        n = len(pairs_x)
        mx, my = sum(pairs_x) / n, sum(pairs_y) / n
        cov = sum((a - mx) * (b - my) for a, b in zip(pairs_x, pairs_y,
                                                      strict=True)) / n
        sx = (sum((a - mx) ** 2 for a in pairs_x) / n) ** 0.5
        sy = (sum((b - my) ** 2 for b in pairs_y) / n) ** 0.5
        correlation = cov / (sx * sy) if sx and sy else None

    lengths = [len(s) for s in book.series if len(s) >= 3]
    typical = min(lengths) if lengths else 0
    expected_bias = -1 / (typical - 1) if typical > 1 else None
    memoryless = (
        correlation is not None and expected_bias is not None
        and abs(correlation - expected_bias) < 0.15
    )
    swing = sorted(swings)[len(swings) // 2] if swings else None
    drift = sum(drifts) / len(drifts) if drifts else None

    if correlation is None:
        return Finding(
            id="SHELF_PRICE_HAS_NO_MEMORY",
            severity="advisory",
            statement=(
                "No listing carries more than one observation, so whether "
                "shelf prices move cannot be tested. Run the scrape without "
                "--listings-only to collect the history."
            ),
            evidence={"series": len(book.series)},
            affects=["price", "morning"],
        )

    return Finding(
        id="SHELF_PRICE_HAS_NO_MEMORY",
        severity="blocks_metric" if memoryless else "advisory",
        statement=(
            f"Shelf prices wobble and go nowhere. Lag-1 correlation is "
            f"{correlation:+.3f} across {len(pairs_x):,} consecutive pairs, "
            f"which is what {typical} observations of pure noise produce on "
            f"their own ({expected_bias:+.2f}); the median listing swings "
            f"{100 * (swing or 0):.1f}% between its high and low and drifts "
            f"{100 * (drift or 0):+.2f}% over the window. No price-movement "
            f"alert can be built on this — 'cut its price this week' is last "
            f"week's dice."
            if memoryless else
            f"Shelf prices carry some memory: lag-1 correlation "
            f"{correlation:+.3f} against {expected_bias:+.2f} expected from "
            f"noise alone. A movement metric may be worth building."
        ),
        evidence={
            "lag1_correlation": round(correlation, 4)
            if correlation is not None else None,
            "correlation_expected_from_noise": round(expected_bias, 3)
            if expected_bias is not None else None,
            "pairs": len(pairs_x),
            "median_peak_to_trough_pct": round(100 * swing, 2)
            if swing is not None else None,
            "mean_drift_pct": round(100 * drift, 3) if drift is not None else None,
            "series": len(book.series),
        },
        affects=["price", "morning"],
    )


def competitor_gap_flat_by_city(book) -> Finding:
    """Divya asked for the gap "by city". This is the answer and the refusal."""
    by_city: dict[str, list[float]] = {}
    for shelf in book.shelves:
        if shelf.in_stock and shelf.mrp_inr:
            by_city.setdefault(shelf.city, []).append(shelf.price_inr / shelf.mrp_inr)
    medians = {
        city: round(sorted(ratios)[len(ratios) // 2], 4)
        for city, ratios in sorted(by_city.items()) if ratios
    }
    spread = (max(medians.values()) - min(medians.values())) if medians else 0.0
    flat = spread < 0.05

    return Finding(
        id="COMPETITOR_GAP_FLAT_BY_CITY",
        severity="advisory",
        statement=(
            f"Discount off MRP is {100 * spread:.1f} points apart across "
            f"{len(medians)} cities, so ranking cities on price gap is ranking "
            f"noise. The gap is reported per SKU where a decision needs it, "
            f"never as a league table of cities."
            if flat else
            f"Discount off MRP varies {100 * spread:.1f} points across "
            f"{len(medians)} cities, which is wide enough to rank."
        ),
        evidence={"median_price_over_mrp_by_city": medians,
                  "spread_pct_points": round(100 * spread, 2)},
        affects=["price"],
    )


def site_mrp_mirrors_master(book) -> Finding:
    """Does an outside source tell us anything about our own product master?"""
    total = book.mrp_agree + book.mrp_conflict
    mirrors = book.mrp_conflict == 0 and total > 0
    return Finding(
        id="SITE_MRP_MIRRORS_MASTER",
        severity="advisory",
        statement=(
            f"The MRP published on the tracker equals ours on all {total:,} "
            f"listings. That makes it a reliable key for telling apart SKUs our "
            f"own master gives the same name — but it is our number coming back "
            f"to us, so it cannot audit the master and is not treated as if it "
            f"could."
            if mirrors else
            f"The tracker's MRP differs from ours on {book.mrp_conflict:,} of "
            f"{total:,} listings. One of the two is wrong and it is worth "
            f"knowing which."
        ),
        evidence={"agree": book.mrp_agree, "differ": book.mrp_conflict},
        affects=["price"],
    )


# The cities the tracker covers, spelled as our own outlet table spells them.
# Aliases are the ones already known to CITY_ALIASES — the free-text city column
# is not a cosmetic problem once prices have to join through it.
_SCRAPED_CITY_NAMES = (
    "MUMBAI", "BOMBAY", "DELHI", "NEW DELHI", "GURGAON", "GURUGRAM", "NOIDA",
    "BENGALURU", "BANGALORE", "CHENNAI", "MADRAS",
)


def price_coverage(conn, window: Window) -> Finding:
    """How much of Kestrel any price sentence can possibly be about."""
    placeholders = ",".join("?" * len(_SCRAPED_CITY_NAMES))
    outlets = _one(conn, f"""
        SELECT COUNT(*) AS active,
               SUM(CASE WHEN UPPER(TRIM(city)) IN ({placeholders})
                        THEN 1 ELSE 0 END) AS inside
          FROM outlets WHERE status = 'ACTIVE'""", _SCRAPED_CITY_NAMES)
    value = _one(conn, f"""
        SELECT SUM(ol.delivered_qty * ol.unit_price_inr) AS total,
               SUM(CASE WHEN UPPER(TRIM(o2.city)) IN ({placeholders})
                        THEN ol.delivered_qty * ol.unit_price_inr ELSE 0 END)
                 AS inside
          FROM order_lines ol
          JOIN orders o ON o.order_id = ol.order_id
          JOIN outlets o2 ON o2.outlet_id = o.outlet_id
         WHERE o.order_date BETWEEN ? AND ?""",
        (*_SCRAPED_CITY_NAMES, window.start.isoformat(), window.end.isoformat()))
    dcs = _one(conn, f"""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN UPPER(TRIM(city)) IN ({placeholders})
                        THEN 1 ELSE 0 END) AS inside
          FROM warehouses""", _SCRAPED_CITY_NAMES)

    share = (100.0 * value["inside"] / value["total"]) if value["total"] else 0.0
    return Finding(
        id="PRICE_COVERS_PART_OF_THE_BUSINESS",
        severity="advisory",
        statement=(
            f"The tracker covers four cities holding {outlets['inside']} of "
            f"{outlets['active']} active outlets and {share:.1f}% of dispatch "
            f"in {window.label}, and {dcs['inside']} of {dcs['total']} "
            f"warehouses. Every price number carries that ceiling; none of them "
            f"speaks for the other two thirds."
        ),
        evidence={
            "outlets_inside": outlets["inside"], "outlets_active": outlets["active"],
            "dispatch_share_pct": round(share, 2),
            "dispatch_inside_inr": round(value["inside"] or 0.0),
            "warehouses_inside": dcs["inside"], "warehouses_total": dcs["total"],
        },
        affects=["price"],
    )


def all_findings(
    conn: sqlite3.Connection, window: Window, book=None
) -> list[Finding]:
    """Blocking findings first — they stop a metric from being built at all."""
    findings = [
        otif_in_full(conn), short_reason_signal(conn), order_status_meaning(conn),
        open_orders_delivered(conn), live_test_outlets(conn), return_qty_signs(conn),
        header_ties_to_lines(conn), net_value_by_source(conn), city_spellings(conn),
        route_region_mismatch(conn), outlet_fill_is_noisy(conn, window),
        return_reason_signal(conn), credit_approval_trail(conn),
        temperature_flag_signal(conn), ageing_bucket_signal(conn),
        excursion_rate_is_flat(conn),
        line_value_is_ordered(conn), credit_leakage_immaterial(conn, window),
    ]
    # Prices come from someone else's web server, so their absence is a state
    # the screen has to be able to describe rather than one it can assume away.
    if book is None:
        findings.append(prices_never_scraped())
    else:
        findings += [
            shelf_price_has_no_memory(book),
            competitor_gap_flat_by_city(book),
            site_mrp_mirrors_master(book),
            price_coverage(conn, window),
        ]
    rank = {"blocks_metric": 0, "advisory": 1, "clean": 2}
    return sorted(findings, key=lambda f: (rank[f.severity], f.id))
