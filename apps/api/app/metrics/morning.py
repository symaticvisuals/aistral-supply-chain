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

from app.metrics import expiry, money
from app.metrics.scope import outlet_filter
from app.metrics.windows import Window

Severity = Literal["breach", "watch", "info"]

LATE_MINUTES = 120  # "over two hours late", the threshold in the brief

# Chilled rides at 2-4C. 8C is the point past which a load is a conversation
# rather than a wobble — set here, in one place, because it is a judgement and
# Divya may want it somewhere else.
CHILLED_BAND_MAX = 8.0

# The data gives us a peak temperature and no duration, so 8-12C cannot be
# called: an hour at 9C is nothing, a day at 9C is not. Above 12C duration
# stops mattering. That is the honest line between "look at this" and "this
# stock is gone", and it is why the two get different tiers.
CHILLED_SPOILED = 12.0

# A morning list nobody finishes is a morning list nobody opens.
MAX_CASES_LISTED = 6

# A stock refusal to modern trade is worse than the same refusal to a kirana:
# MT fines on units short, so it costs money as well as service.
PENALISING_CHANNEL = "MT"

# Half a DC's drops late stops being a delivery problem and starts being the DC.
DC_SYSTEMIC_SHARE = 50.0

# A SKU short here is one stock fix that clears every shop on the line.
CONCENTRATED_SHOPS = 5

# What to do about a case, in the order Divya should work them.
ACT, DECIDE, PATTERN = "act", "decide", "pattern"
PRIORITY_RANK = {ACT: 0, DECIDE: 1, PATTERN: 2}
PRIORITY_LABEL = {
    ACT: "Act before noon",
    DECIDE: "Decide today",
    PATTERN: "Pattern",
}

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
    # How many cases exist. The list may be a short working set of that.
    population: int = 0
    # The worst of its cases, and how many of them need doing this morning.
    priority: str = "pattern"
    act_now: int = 0


def latest_day(conn: sqlite3.Connection) -> dt.date:
    row = conn.execute("SELECT MAX(order_date) AS d FROM orders").fetchone()
    return dt.date.fromisoformat(row["d"][:10])


def earliest_day(conn: sqlite3.Connection) -> dt.date:
    row = conn.execute("SELECT MIN(order_date) AS d FROM orders").fetchone()
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
    """Chilled stock that rode too warm, measured rather than flagged.

    `temperature_excursion_flag` is not used. It fires on 3.1% of deliveries in
    every temperature band — under 2C, in band, and over 12C alike — so it is a
    coin flip, not a reading (see quality.temperature_flag_signal). Trusting it
    both invents excursions on ambient loads and hides real ones: on 30 Jun 2026
    it caught 4 deliveries while 28 chilled loads actually rode above the band,
    and the two sets overlapped on one.

    So the event is computed from what the truck reported and what was on it:
    chilled lines, actually delivered, above CHILLED_BAND_MAX. Ranked by the
    value at risk, because that is the number that decides whether it is worth
    a van.
    """
    rc, args = _args(day, region_id)
    args.append(CHILLED_BAND_MAX)
    rows = conn.execute(
        f"""SELECT d.delivery_note_number AS ref, ot.outlet_name AS outlet,
                   r.route_code AS route,
                   ROUND(d.max_temp_celsius, 1) AS max_temp_c,
                   d.delay_minutes AS delay_minutes,
                   d.vehicle_registration AS vehicle,
                   d.temperature_excursion_flag AS vendor_flag,
                   ROUND(SUM(CASE WHEN p.is_chilled = 1
                        THEN ol.delivered_qty * ol.unit_price_inr
                             * (1 - COALESCE(ol.line_discount_pct, 0) / 100.0)
                        END)) AS chilled_value_inr
              FROM deliveries d
              JOIN orders o ON o.order_id = d.order_id
              JOIN outlets ot ON ot.outlet_id = o.outlet_id
              JOIN routes r ON r.route_id = d.route_id
              JOIN order_lines ol ON ol.order_id = d.order_id
              JOIN products p ON p.product_id = ol.product_id
             WHERE o.order_date = ? {rc}
               AND {outlet_filter()}
               AND d.max_temp_celsius > ?
             GROUP BY d.delivery_id
             HAVING chilled_value_inr > 0
             ORDER BY d.max_temp_celsius > {CHILLED_SPOILED} DESC,
                      chilled_value_inr DESC""",
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

    at_risk = sum(i["chilled_value_inr"] for i in items)
    missed_by_vendor = sum(1 for i in items if not i["vendor_flag"])
    spoiled = sum(1 for i in items if i["max_temp_c"] > CHILLED_SPOILED)
    return Event(
        kind="cold_chain",
        severity="breach",
        headline=f"{len(rows)} chilled load(s) above {CHILLED_BAND_MAX:.0f}C",
        owner="Cold chain",
        detail=(
            f"Rs {at_risk:,.0f} of chilled stock rode warm and is sitting in shops "
            f"now, {spoiled} of it above {CHILLED_SPOILED:.0f}C. Measured from the "
            f"temperature the truck reported, not from temperature_excursion_flag, "
            f"which fires at the same rate whatever the reading — it missed "
            f"{missed_by_vendor} of these. There is no duration in the data, so "
            f"8-12C is a look and above 12C is a write-off."
        ),
        items=items[:MAX_CASES_LISTED],
        population=len(items),
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
        population=len(flagged),
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
                  owner=owner, detail=detail, items=items,
                  population=len(items))
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
        population=len(rows),
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
        population=queue.notes_n,
    )


def expiring_stock(conn, day, region_id) -> Event | None:
    """Stock on the rack that will not move before it expires.

    Standing, not a day event: it comes from a weekly snapshot and it was true
    before this morning started. It is also the only forward-looking thing on
    the screen — everything else here already happened.

    Region means the *warehouse's* region here, because this is physical stock
    in a DC. Everywhere else region means the shop's.
    """
    risk = expiry.at_risk(conn, day, region_id)
    if not risk.lines:
        return None

    detail = (
        f"Rs {risk.doomed_value_inr:,.0f} across {risk.doomed_lines} lines cannot "
        f"sell through before it expires — the depot holds more than it can move "
        f"in the days remaining. A further {risk.near_lines} lines expire within "
        f"{expiry.NEAR_DAYS} days."
    )
    if risk.is_stale:
        detail += (
            f" The stock position is {risk.snapshot_age_days} days old, so treat "
            f"these as leads rather than counts."
        )
    else:
        detail += f" Counted from the {risk.snapshot_date} snapshot."
    return Event(
        kind="expiring_stock",
        severity="watch",
        headline=(
            f"{risk.doomed_cases:,} cases will expire before they sell"
            if risk.doomed_lines
            else f"{risk.near_cases:,} cases expire within {expiry.NEAR_DAYS} days"
        ),
        owner="Planning",
        detail=detail,
        items=[line.__dict__ for line in risk.lines],
        population=risk.doomed_lines or risk.near_lines,
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


def _natural_id(item: dict) -> str:
    if item.get("batch") and item.get("warehouse"):
        return f"{item['warehouse']}/{item['batch']}"
    for key in ("ref", "warehouse", "sku", "product"):
        if item.get(key) is not None:
            return str(item[key])
    raise ValueError(f"item has no stable id: {item!r}")


def case_priority(kind: str, item: dict) -> str:
    """What to do about this case today.

    Deliberately not a score. These cases are not commensurable — a warm load is
    spoiled rupees, a refusal is units never sent, a late drop lost nothing
    because the goods arrived. Averaging them into one number would be the same
    dishonesty as blending case fill with each fill. So the question asked here
    is the one Divya actually asks: can what I do this morning still change the
    outcome, or is this only a trend?
    """
    if kind == "cold_chain":
        # Above 12C the load is gone whatever the duration was — that is a
        # write-off to raise today. Between 8 and 12 it turns on how long it sat
        # there, which this data does not record, so somebody has to look.
        temp = item.get("max_temp_c") or 0
        return ACT if temp > CHILLED_SPOILED else DECIDE
    if kind == "late_delivery":
        late_pct = item.get("late_pct") or 0
        # Nothing was lost — it arrived. One late drop is a trend; half a DC's
        # drops is the DC, and that is a conversation to have this morning.
        return DECIDE if late_pct >= DC_SYSTEMIC_SHARE else PATTERN
    if kind == "stockout_refusal":
        # The shop got nothing and we can still ship. Always today's problem.
        return ACT
    if kind == "credit_refusal":
        # Finance chose this. Supply chain cannot unblock it.
        return DECIDE
    if kind == "sku_short":
        shops = item.get("shops") or 0
        return ACT if shops >= CONCENTRATED_SHOPS else PATTERN
    if kind == "credit_backlog":
        # A decision queue by definition. Nothing to fix, something to rule on.
        return DECIDE
    if kind == "expiring_stock":
        # Still saveable — transfer it, promote it, or write it down. But the
        # snapshot is weekly, so this is a decision to take today, not a call
        # to make before noon.
        return DECIDE
    return PATTERN


def item_label(kind: str, item: dict) -> str:
    """One line a person can read. Not a dump of every column."""
    if kind == "cold_chain":
        temp = item.get("max_temp_c")
        name = item.get("outlet") or item.get("ref")
        value = item.get("chilled_value_inr")
        if value is not None and temp is not None:
            return f"{name}, Rs {value:,.0f} chilled at {temp}C"
        return f"{name}, {temp}C" if temp is not None else str(name)
    if kind == "late_delivery":
        return (
            f"{item.get('warehouse')}, {item.get('late')} of "
            f"{item.get('drops')} drops late"
        )
    if kind in ("stockout_refusal", "credit_refusal"):
        units = item.get("units")
        qty = f"{int(units):,}" if units is not None else "?"
        channel = item.get("channel") or ""
        return f"{item.get('outlet')}, {qty} units, {channel}".rstrip(", ")
    if kind == "sku_short":
        short = item.get("units_short")
        qty = f"{int(short):,}" if short is not None else "?"
        return f"{item.get('product')}, {item.get('shops')} shops, {qty} short"
    if kind == "expiring_stock":
        return (
            f"{item.get('product')} at {item.get('warehouse')}, "
            f"{item.get('on_hand_cases'):,} cases, {item.get('days_left')} days left"
        )
    if kind == "credit_backlog":
        value = item.get("value_inr")
        money = f"Rs {value:,.0f}" if value is not None else ""
        return f"{item.get('outlet')}, {item.get('days_waiting')} days, {money}".rstrip(
            ", "
        )
    return str(item.get("ref") or item.get("product") or "?")


def stamp(event: Event) -> Event:
    for item in event.items:
        item["case_id"] = f"{event.kind}:{_natural_id(item)}"
        item["label"] = item_label(event.kind, item)
        item["priority"] = case_priority(event.kind, item)
    # Cases inside a category can differ — one DC late on every drop sits above
    # one late on three. Sort them, then let the category inherit its worst.
    event.items.sort(key=lambda i: PRIORITY_RANK[i["priority"]])
    event.priority = (
        event.items[0]["priority"] if event.items else PATTERN
    )
    event.act_now = sum(1 for i in event.items if i["priority"] == ACT)
    if not event.population:
        event.population = len(event.items)
    return event


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
    standing = [
        expiring_stock(conn, day, region_id),
        credit_backlog(conn, day, region_id),
    ]
    # Worst case first, then how many cases of that kind need doing. Severity
    # is kept on each event but no longer decides the order: it is assigned per
    # category, and the question here is per case.
    ranked = lambda es: sorted(  # noqa: E731
        (stamp(e) for e in es if e is not None),
        key=lambda e: (PRIORITY_RANK[e.priority], -e.act_now, _RANK[e.severity]),
    )
    return {
        "as_of": day.isoformat(),
        "is_latest": day == latest_day(conn),
        "earliest": earliest_day(conn).isoformat(),
        "latest": latest_day(conn).isoformat(),
        "day": day_summary(conn, day, region_id),
        "events": [e.__dict__ for e in ranked(events)],
        "standing": [e.__dict__ for e in ranked(standing)],
        "priorities": [
            {"id": key, "label": PRIORITY_LABEL[key]}
            for key in (ACT, DECIDE, PATTERN)
        ],
        "notes": [
            "Events, not rates. At ~150 orders a day an outlet places about one, "
            "so a per-shop daily fill rate is one order's luck.",
            "Cases are tiered by whether this morning can still change the "
            "outcome, not by a blended score. A warm load is spoiled rupees, a "
            "refusal is units never sent, a late drop lost nothing — those do "
            "not add up, so they are not added up.",
            "'Late' has two sources that disagree on a third of deliveries. Both "
            "counts are given; neither is presented as the answer.",
            "Standing items were already true this morning. They are listed apart "
            "from the day so a carried-over pile is never read as fresh damage.",
        ],
    }
