"""What happened yesterday, as things to do rather than a rate to read.

A quarterly fill rate is a board number. On a Tuesday morning it is a constant,
and it names no action. This module answers the other question — what broke
yesterday, who owns it, and what is worth a phone call before noon.

The grain matters. At roughly 150 orders a day nationally an outlet places about
one order, so a per-shop daily fill rate is a single order's luck. Daily rates
are noise; daily *events* are facts. Everything here is an event with an owner.
"""

import datetime as dt
import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from app.metrics import money
from app.metrics.scope import outlet_filter
from app.metrics.windows import Window

Severity = Literal["breach", "watch", "info"]

LATE_MINUTES = 120  # "over two hours late", the threshold in the brief

# TELEMATICS_A writes ISO; TELEMATICS_B writes 01-Apr-2025 01:00 PM. Neither is
# wrong, they are just different vendors, so parse both and never assume.
_ARRIVAL_FORMATS = ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %I:%M %p", "%Y-%m-%d %H:%M")


def parse_arrival(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    for fmt in _ARRIVAL_FORMATS:
        try:
            return dt.datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


@dataclass
class Event:
    kind: str
    severity: Severity
    headline: str
    owner: str
    detail: str = ""
    items: list[dict] = field(default_factory=list)


def latest_day(conn: sqlite3.Connection) -> dt.date:
    row = conn.execute("SELECT MAX(order_date) AS d FROM orders").fetchone()
    return dt.date.fromisoformat(row["d"][:10])


def resolve_as_of(conn: sqlite3.Connection, spec: str | None) -> dt.date:
    """The day being reported on.

    The pack is frozen, so this can never come from the wall clock. It defaults
    to the last day with data and is overridable, which is also what makes a
    past incident reproducible.
    """
    if not spec:
        return latest_day(conn)
    try:
        return dt.date.fromisoformat(spec)
    except ValueError as exc:
        raise ValueError(f"as_of must be YYYY-MM-DD, got {spec!r}") from exc


def _args(day: dt.date, region_id: int | None) -> tuple[str, list]:
    clause = "AND o.region_id = ?" if region_id is not None else ""
    args: list = [day.isoformat()]
    if region_id is not None:
        args.append(region_id)
    return clause, args


def cold_chain(conn, day, region_id) -> Event | None:
    """A chilled load that went warm. Always worth a call — it is silent money."""
    rc, args = _args(day, region_id)
    rows = conn.execute(
        f"""SELECT d.delivery_note_number AS ref, ot.outlet_name AS outlet,
                   r.route_code AS route, d.max_temp_celsius AS max_temp_c,
                   d.delay_minutes AS delay_minutes,
                   d.vehicle_registration AS vehicle
              FROM deliveries d
              JOIN orders o ON o.order_id = d.order_id
              JOIN outlets ot ON ot.outlet_id = o.outlet_id
              JOIN routes r ON r.route_id = d.route_id
             WHERE o.order_date = ? {rc}
               AND {outlet_filter()}
               AND d.temperature_excursion_flag = 1
             ORDER BY d.max_temp_celsius DESC""",
        args,
    ).fetchall()
    if not rows:
        return None

    items = []
    for r in rows:
        item = dict(r)
        # An excursion on a truck that arrived early is a cooling fault, not a
        # scheduling one. Different team, different fix — worth saying out loud.
        if r["delay_minutes"] is not None and r["delay_minutes"] <= 0:
            item["note"] = (
                f"Arrived on time or early, so this is the unit on "
                f"{r['vehicle']}, not the schedule."
            )
        items.append(item)

    return Event(
        kind="cold_chain",
        severity="breach",
        headline=f"{len(rows)} chilled delivery(s) went warm",
        owner="Cold chain",
        detail="Chilled stock rides at 2-4C. Anything above that is spoilage "
               "nobody has noticed yet.",
        items=items,
    )


def late_deliveries(conn, day, region_id) -> Event | None:
    """Lateness grouped by warehouse, because a warehouse has a manager.

    Grouping by route looked obvious and was useless: with ~120 drops spread
    over 140 routes most routes carry one drop, so "47 routes late" is a number
    nobody can act on. Eight DCs is a list you can work through before noon.

    "Late" also has two sources that disagree on direction for a third of all
    deliveries, so both counts travel with the event. Picking one silently is
    the habit this product exists to break.
    """
    rc, args = _args(day, region_id)
    rows = conn.execute(
        f"""SELECT w.warehouse_code AS warehouse, w.warehouse_name AS name,
                   r.route_code AS route, d.delay_minutes,
                   d.planned_arrival, d.actual_arrival
              FROM deliveries d
              JOIN orders o ON o.order_id = d.order_id
              JOIN outlets ot ON ot.outlet_id = o.outlet_id
              JOIN routes r ON r.route_id = d.route_id
              JOIN warehouses w ON w.warehouse_id = d.warehouse_id
             WHERE o.order_date = ? {rc} AND {outlet_filter()}""",
        args,
    ).fetchall()
    if not rows:
        return None

    by_wh: dict[str, dict] = {}
    late_reported = late_timestamps = 0
    for r in rows:
        slot = by_wh.setdefault(
            r["warehouse"],
            {"warehouse": r["warehouse"], "name": r["name"], "drops": 0,
             "late": 0, "worst_minutes": 0, "worst_route": None},
        )
        slot["drops"] += 1

        reported = r["delay_minutes"]
        planned, actual = parse_arrival(r["planned_arrival"]), parse_arrival(
            r["actual_arrival"]
        )
        derived = (
            (actual - planned).total_seconds() / 60 if planned and actual else None
        )
        if reported is not None and reported > LATE_MINUTES:
            late_reported += 1
        if derived is not None and derived > LATE_MINUTES:
            late_timestamps += 1

        # Flag if either source calls it late: on a morning list a false positive
        # costs a phone call, a miss costs a customer.
        worst = max([v for v in (reported, derived) if v is not None], default=0)
        if worst > LATE_MINUTES:
            slot["late"] += 1
            if worst > slot["worst_minutes"]:
                slot["worst_minutes"] = round(worst)
                slot["worst_route"] = r["route"]

    flagged = sorted(
        (s for s in by_wh.values() if s["late"]),
        key=lambda s: (-s["late"], -s["worst_minutes"]),
    )
    if not flagged:
        return None
    for s in flagged:
        s["late_pct"] = round(100.0 * s["late"] / s["drops"], 1)

    total = len(rows)
    share = 100.0 * max(late_reported, late_timestamps) / total
    worst_dc = flagged[0]
    return Event(
        kind="late_delivery",
        severity="breach" if share >= 20 else "watch",
        headline=(
            f"{worst_dc['warehouse']} worst: {worst_dc['late']} of "
            f"{worst_dc['drops']} drops over {LATE_MINUTES // 60}h late"
        ),
        owner="Transport",
        detail=(
            f"Across {total} drops, delay_minutes counts {late_reported} late and "
            f"the planned/actual timestamps count {late_timestamps}. Those two "
            f"fields disagree on a third of deliveries in this dataset, so both "
            f"are shown and neither is called the answer."
        ),
        items=flagged,
    )


def refusals(conn, day, region_id) -> list[Event]:
    """Orders we turned down. Split by who actually owns the decision."""
    rc, args = _args(day, region_id)
    rows = conn.execute(
        f"""SELECT o.cancelled_reason_code AS reason, o.order_number AS ref,
                   ot.outlet_name AS outlet, ot.channel,
                   ROUND(SUM(CASE WHEN ol.qty_uom = 'EACH' THEN ol.ordered_qty
                        ELSE ol.ordered_qty * ol.case_pack_at_order END)) AS units
              FROM orders o
              JOIN outlets ot ON ot.outlet_id = o.outlet_id
              JOIN order_lines ol ON ol.order_id = o.order_id
             WHERE o.order_date = ? {rc} AND {outlet_filter()}
               AND o.order_status = 'CANCELLED'
               AND o.cancelled_reason_code IN ('CR03_NO_STOCK', 'CR01_CREDIT')
             GROUP BY o.order_id, o.cancelled_reason_code, o.order_number,
                      ot.outlet_name, ot.channel
             ORDER BY units DESC""",
        args,
    ).fetchall()

    out: list[Event] = []
    for reason, kind, owner, severity, label in (
        ("CR03_NO_STOCK", "stockout_refusal", "Supply chain", "breach",
         "refused for no stock"),
        ("CR01_CREDIT", "credit_refusal", "Finance", "watch",
         "refused on credit hold"),
    ):
        items = [dict(r) for r in rows if r["reason"] == reason]
        if not items:
            continue
        units = sum(i["units"] or 0 for i in items)
        mt = sum(1 for i in items if i["channel"] == "MT")
        detail = f"{units:,.0f} units the shop asked for and did not get."
        if reason == "CR03_NO_STOCK":
            detail += " Nobody failed to deliver these — the stock was not there."
        else:
            detail += " A commercial decision, not a supply failure."
        if mt:
            detail += f" {mt} of them are modern trade, which fines on units short."
        out.append(
            Event(kind=kind, severity=severity,
                  headline=f"{len(items)} order(s) {label}",
                  owner=owner, detail=detail, items=items)
        )
    return out


def sku_shortfalls(conn, day, region_id, top: int = 5) -> Event | None:
    """The SKUs hitting the most shops today.

    The highest-leverage line on the page: one stock fix clears every shop on it,
    where calling those shops individually clears none of them.

    Ranked rather than thresholded, and deliberately so. A "short at 3+ shops"
    filter matched 113-185 SKUs a day here, so the headline count was really just
    the page size — it looked like a shortlist and was a catalogue. The true
    population travels with the event so the top five are never mistaken for all
    of them.
    """
    rc, args = _args(day, region_id)
    rows = conn.execute(
        f"""SELECT p.product_name AS product, p.sku_code AS sku,
                   p.storage_temp_band AS band,
                   COUNT(DISTINCT o.outlet_id) AS shops,
                   ROUND(SUM(CASE WHEN ol.qty_uom = 'EACH'
                        THEN ol.ordered_qty - ol.delivered_qty
                        ELSE (ol.ordered_qty - ol.delivered_qty)
                             * ol.case_pack_at_order END)) AS units_short
              FROM orders o
              JOIN order_lines ol ON ol.order_id = o.order_id
              JOIN products p ON p.product_id = ol.product_id
              JOIN outlets ot ON ot.outlet_id = o.outlet_id
             WHERE o.order_date = ? {rc} AND {outlet_filter()}
               AND o.order_status IN ('DELIVERED', 'PARTIAL')
               AND ol.delivered_qty < ol.ordered_qty
             GROUP BY p.product_id, p.product_name, p.sku_code, p.storage_temp_band
             ORDER BY shops DESC, units_short DESC""",
        args,
    ).fetchall()
    if not rows:
        return None

    worst = rows[0]
    concentrated = [r for r in rows if r["shops"] >= 5]
    return Event(
        kind="sku_short",
        severity="breach" if worst["shops"] >= 6 else "watch",
        headline=f"{worst['product']} short at {worst['shops']} shops",
        owner="Supply chain",
        detail=(
            f"{len(rows)} SKUs came up short somewhere today; {len(concentrated)} "
            f"of them at five shops or more. These are the ones hitting the most "
            f"shops at once — one stock fix clears every shop on the line."
        ),
        items=[dict(r) for r in rows[:top]],
    )


def credit_backlog(conn, day, region_id) -> Event | None:
    """Credit notes nobody has ruled on. A standing pile, not yesterday's news.

    Every other event here is something that happened on the day. This one is
    deliberately not: it is the money equivalent of an unread inbox, and a window
    would hide exactly the notes that have been sitting longest. It is labelled
    as a backlog so nobody reads it as a fresh failure, and the count raised on
    the day travels with it so the trend is visible.
    """
    queue = money.pending_queue(conn, day, region_id)
    if not queue.notes_n:
        return None

    today = Window("day", day.isoformat(), day, day)
    raised_today = money.credit_notes(conn, today, region_id).undecided_n

    detail = (
        f"Rs {queue.value_inr:,.0f} raised against us that nobody has approved or "
        f"rejected. Not a decision either way, so it sits off both the loss and "
        f"the dispute."
    )
    if queue.stale_n:
        detail += (
            f" Rs {queue.stale_inr:,.0f} of it across {queue.stale_n} notes has "
            f"been waiting over a year."
        )
    detail += (
        f" {raised_today} came in on this day."
        if raised_today
        else " None came in on this day, so this is entirely carried over."
    )
    # Listed by value: the oldest notes here are worth tens of rupees, so an
    # age-sorted list would look like a work queue without being one. Age rides
    # on every row instead. approval_date is empty on every row in this table,
    # so how long the desk has actually held a note cannot be measured — age is
    # from the return date and no further.
    return Event(
        kind="credit_backlog",
        severity="watch",
        headline=(
            f"{queue.notes_n} credit notes undecided, oldest "
            f"{queue.oldest_days} days"
        ),
        owner="Credit desk",
        detail=detail,
        items=money.pending_to_work(conn, day, region_id),
    )


def day_summary(conn, day, region_id) -> dict:
    rc, args = _args(day, region_id)
    orders = conn.execute(
        f"""SELECT COUNT(DISTINCT o.order_id) AS orders,
                   ROUND(SUM(CASE WHEN ol.qty_uom = 'EACH'
                        THEN ol.ordered_qty - ol.delivered_qty
                        ELSE (ol.ordered_qty - ol.delivered_qty)
                             * ol.case_pack_at_order END)) AS units_short
              FROM orders o
              JOIN order_lines ol ON ol.order_id = o.order_id
              JOIN outlets ot ON ot.outlet_id = o.outlet_id
             WHERE o.order_date = ? {rc} AND {outlet_filter()}
               AND o.order_status IN ('DELIVERED', 'PARTIAL')""",
        args,
    ).fetchone()

    deliveries = conn.execute(
        f"""SELECT d.delay_minutes, d.planned_arrival, d.actual_arrival
              FROM deliveries d
              JOIN orders o ON o.order_id = d.order_id
              JOIN outlets ot ON ot.outlet_id = o.outlet_id
             WHERE o.order_date = ? {rc} AND {outlet_filter()}""",
        args,
    ).fetchall()

    reported = timestamps = 0
    for r in deliveries:
        if r["delay_minutes"] is not None and r["delay_minutes"] > LATE_MINUTES:
            reported += 1
        p, a = parse_arrival(r["planned_arrival"]), parse_arrival(r["actual_arrival"])
        if p and a and (a - p).total_seconds() / 60 > LATE_MINUTES:
            timestamps += 1

    return {
        "orders": orders["orders"] or 0,
        "units_short": orders["units_short"] or 0,
        "deliveries": len(deliveries),
        "late_over_2h_by_delay_field": reported,
        "late_over_2h_by_timestamps": timestamps,
    }


_RANK = {"breach": 0, "watch": 1, "info": 2}


def morning(conn, day: dt.date, region_id: int | None = None) -> dict:
    """Two lists, kept apart on purpose.

    `events` is what happened on this day, and an empty one is a real answer —
    a quiet day must not invent work. `standing` is what was already true when
    the day started. Mixing them would let a backlog that reads the same every
    morning sit among yesterday's breaches until nobody sees either.
    """
    events = [
        cold_chain(conn, day, region_id),
        late_deliveries(conn, day, region_id),
        *refusals(conn, day, region_id),
        sku_shortfalls(conn, day, region_id),
    ]
    standing = [credit_backlog(conn, day, region_id)]
    by_severity = lambda es: sorted(  # noqa: E731
        (e for e in es if e is not None), key=lambda e: _RANK[e.severity]
    )
    return {
        "as_of": day.isoformat(),
        "is_latest": day == latest_day(conn),
        "day": day_summary(conn, day, region_id),
        "events": [e.__dict__ for e in by_severity(events)],
        "standing": [e.__dict__ for e in by_severity(standing)],
        "notes": [
            "Events, not rates. At ~150 orders a day an outlet places about one, "
            "so a per-shop daily fill rate is one order's luck.",
            "'Late' has two sources that disagree on a third of deliveries. Both "
            "counts are given; neither is presented as the answer.",
            "Standing items were already true this morning. They are listed apart "
            "from the day so a carried-over pile is never read as fresh damage.",
        ],
    }
