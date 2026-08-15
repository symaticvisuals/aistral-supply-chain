import datetime as dt
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from app import handled
from app.db import get_conn
from app.metrics import expiry as expiry_q
from app.metrics import fill as fill_q
from app.metrics import money as money_q
from app.metrics import morning as morning_q
from app.metrics import prices as prices_q
from app.metrics import quality as quality_q
from app.metrics.compute import decompose, fill_numbers, units_short
from app.metrics.scope import Scope, ScopeError, build_receipt, get_scope
from app.metrics.windows import Window, WindowError, parse_window
from app.schemas import (
    ExpiryResponse,
    FillResponse,
    HandleIn,
    HandleOut,
    MoneyResponse,
    MorningResponse,
    OutletsResponse,
    QualityResponse,
    WindowOut,
)
from app.settings import settings

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _window_out(w: Window) -> WindowOut:
    return WindowOut(
        id=w.id, label=w.label, start=w.start.isoformat(),
        end=w.end.isoformat(), is_latest_complete=w.is_latest_complete,
    )


def _resolve(
    conn: sqlite3.Connection, window: str | None, scope: str | None
) -> tuple[Window, Scope]:
    """Window and scope, or a 400 that says what was wrong. Never a silent default."""
    try:
        return (
            parse_window(window, fill_q.max_order_date(conn)),
            get_scope(scope),
        )
    except (WindowError, ScopeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _region_id(conn: sqlite3.Connection, region: str | None) -> int | None:
    if region is None:
        return None
    row = conn.execute(
        "SELECT region_id FROM regions WHERE UPPER(region_code) = UPPER(?)"
        " OR UPPER(region_name) = UPPER(?)", (region, region),
    ).fetchone()
    if row is None:
        known = conn.execute("SELECT region_code FROM regions ORDER BY 1").fetchall()
        raise HTTPException(
            status_code=400,
            detail=f"Unknown region {region!r}. Known: "
                   f"{', '.join(r['region_code'] for r in known)}.",
        )
    return row["region_id"]


@router.get("/fill", response_model=FillResponse)
def get_fill(
    window: str | None = Query(None, description="'fy26q1', a 'from:to' range, "
                                                 "or omit for latest complete"),
    region: str | None = Query(None, description="Region code, e.g. WST"),
    scope: str | None = Query(None, description="attempted | stockout | "
                                                "kestrel_fault | all_cancels"),
    conn: sqlite3.Connection = Depends(get_conn),
) -> FillResponse:
    w, s = _resolve(conn, window, scope)
    region_id = _region_id(conn, region)

    attempted = fill_q.attempted_sums(conn, w, region_id)
    refused = fill_q.refused_sums(conn, w, s, region_id)
    service = decompose(attempted, refused)
    receipt = build_receipt(conn, w, s, region_id)

    notes = [
        "service_pct is execution_pct x availability_pct. Both factors are "
        "reported because they have different owners.",
        "case_only_pct is what a qty_uom='CASE' filter produces. It is shown so it "
        "can be recognised, not used.",
    ]
    if s.contested:
        notes.append(
            f"This scope counts {', '.join(s.contested)} as Kestrel's fault. That "
            f"is arguable — a credit hold is a finance decision, not a supply "
            f"failure. Compare the 'stockout' rung to see what it costs."
        )
    if receipt.excluded_outlets:
        notes.append(
            f"{len(receipt.excluded_outlets)} outlets excluded and listed by name "
            f"under exclusions. Nothing is dropped silently."
        )

    return FillResponse(
        window=_window_out(w), region=region,
        scope={"id": s.id, "label": s.label,
               "counted_cancel_reasons": list(s.counted_cancel_reasons),
               "contested": list(s.contested)},
        orders_counted=attempted.orders + refused.orders,
        service=service.__dict__,
        fill=fill_numbers(attempted).__dict__,
        units_short=units_short(attempted, refused).__dict__,
        ladder=[r.__dict__ for r in fill_q.ladder(conn, w, region_id)],
        exclusions={
            "excluded_outlets": receipt.excluded_outlets,
            "orders_excluded": receipt.orders_excluded,
            "total_orders_excluded": receipt.total_orders_excluded,
        },
        notes=notes,
    )


@router.get("/fill/outlets", response_model=OutletsResponse)
def get_fill_outlets(
    window: str | None = Query(None),
    region: str | None = Query(None),
    scope: str | None = Query(None),
    limit: int = Query(10, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_conn),
) -> OutletsResponse:
    """Both orderings, always.

    Ranking by fill % and by units short name different shops, and the second is
    where the exposure actually is: an outlet can sit above the national average
    and still be the largest hole in the country. Returning one list would be
    picking a side of an argument the data does not settle.
    """
    w, s = _resolve(conn, window, scope)
    region_id = _region_id(conn, region)
    rows = fill_q.outlet_rows(conn, w, s, region_id)

    by_units = sorted(rows, key=lambda r: -r.units_short)[:limit]
    # Pair the rate with its row so the sort key is a plain float: an outlet with
    # no ask has no rate, and must not be sorted as if it scored zero.
    rated = [(r.case_fill_pct, r) for r in rows if r.case_fill_pct is not None]
    by_fill = [r for _, r in sorted(rated, key=lambda pair: pair[0])][:limit]

    ids_units = {r.outlet_id for r in by_units}
    overlap = sum(1 for r in by_fill if r.outlet_id in ids_units)

    return OutletsResponse(
        window=_window_out(w), region=region,
        scope={"id": s.id, "label": s.label,
               "counted_cancel_reasons": list(s.counted_cancel_reasons),
               "contested": list(s.contested)},
        limit=limit,
        by_units_short=[r.__dict__ for r in by_units],
        by_fill_pct=[r.__dict__ for r in by_fill],
        overlap=overlap,
        exposure={
            "by_units_short": sum(r.units_short for r in by_units),
            "by_fill_pct": sum(r.units_short for r in by_fill),
        },
        notes=[
            f"Two orderings of the same rows, sharing {overlap} of {len(by_units)} "
            f"outlets under this scope.",
            "Overlap is scope-dependent. Under 'attempted' the lists are disjoint: "
            "fill % is driven by how few orders a shop placed, units short by how "
            "much it asked for. Scopes that count refusals pull them together, "
            "because a cancellation damages both measures at once.",
            "A rate-sorted list cannot surface an outlet that is above average and "
            "still the largest hole in the country. That is why neither list is "
            "called the answer.",
        ],
    )


@router.get("/quality", response_model=QualityResponse)
def get_quality(
    window: str | None = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> QualityResponse:
    """What the data does, as opposed to what the dictionary claims.

    Computed per request rather than written down, so a finding can never outlive
    the condition that produced it.
    """
    w, _ = _resolve(conn, window, None)
    findings = quality_q.all_findings(conn, w, prices_q.load(conn))
    return QualityResponse(
        checked_at_window=_window_out(w),
        findings=[f.__dict__ for f in findings],
        blocking=[f.id for f in findings if f.severity == "blocks_metric"],
    )


@router.get("/money", response_model=MoneyResponse)
def get_money(
    window: str | None = Query(None),
    region: str | None = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> MoneyResponse:
    """Credit notes against what actually shipped.

    Divya asked for this as a percentage. It is returned as one, and also as the
    three rupee figures behind it, because on this data the percentage is too
    small to move a decision while the pending pile is large enough to work.
    """
    w, _ = _resolve(conn, window, None)
    region_id = _region_id(conn, region)

    leak = money_q.leakage(conn, w, region_id)
    categories = money_q.by_category(conn, w, region_id)
    pending = money_q.pending_queue(conn, w.end, region_id)

    notes = [
        "Dispatch value is delivered quantity at line price after discount. "
        "line_value_inr prices the ordered quantity and would overstate it.",
        "Credit notes are split by status because a rejected note is not a loss "
        "and a pending one is not yet a decision. Three numbers, no blend.",
        "No breakdown by reason code: the codes carry no signal on this data. "
        "See RETURN_REASON_CODE_NO_SIGNAL in /metrics/quality.",
    ]
    if leak.raised_pct is None:
        notes.append(
            "Nothing dispatched in this window, so the ratio has no denominator. "
            "Reported as null rather than as zero."
        )
    elif not leak.material:
        notes.append(
            f"The ratio is {leak.raised_pct:.2f}% of dispatch, below the "
            f"{money_q.MATERIAL_PCT}% worth watching. Rank on the rupees instead."
        )
    if pending.oldest_days:
        notes.append(
            f"{pending.notes_n} credit notes are still undecided, the oldest "
            f"{pending.oldest_days} days old. That queue is the actionable part."
        )
    if categories:
        top, bottom = categories[0], categories[-1]
        notes.append(
            f"Categories sit close together — {top.category} leads and "
            f"{bottom.category} trails, so no single category is the problem."
        )

    return MoneyResponse(
        window=_window_out(w), region=region,
        dispatch_inr=leak.dispatch_inr,
        credit_notes={
            **leak.notes.__dict__,
            "exposed_inr": leak.notes.exposed_inr,
            "raised_inr": leak.notes.raised_inr,
        },
        settled_pct=leak.settled_pct,
        exposed_pct=leak.exposed_pct,
        raised_pct=leak.raised_pct,
        ratio_is_material=leak.material,
        by_category=[c.__dict__ for c in categories],
        pending_queue={
            "notes_n": pending.notes_n,
            "value_inr": pending.value_inr,
            "oldest_date": (
                pending.oldest_date.isoformat() if pending.oldest_date else None),
            "oldest_days": pending.oldest_days,
            "stale_n": pending.stale_n,
            "stale_inr": pending.stale_inr,
        },
        notes=notes,
    )


@router.get("/expiry", response_model=ExpiryResponse)
def get_expiry(
    as_of: str | None = Query(None, description="YYYY-MM-DD; omit for the "
                                                "last day with data"),
    region: str | None = Query(None),
    limit: int = Query(10, ge=1, le=500),
    conn: sqlite3.Connection = Depends(get_conn),
) -> ExpiryResponse:
    """Stock that will not sell before it expires.

    The only forward-looking thing here. Everything else in this service reports
    what already went wrong; this says what is about to, while a transfer or a
    promotion can still change it.
    """
    try:
        day = morning_q.resolve_as_of(conn, as_of or settings.as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    region_id = _region_id(conn, region)
    risk = expiry_q.at_risk(conn, day, region_id, limit)

    notes = [
        "Value is on-hand cases at list price, which is per each in this data.",
        "'Cannot sell through' means days_of_cover exceeds the days left before "
        "expiry. days_of_cover tops out at 40 here, so the test cannot flag a "
        "slow mover with three months left — that bound is real, not a choice.",
        "ageing_bucket is ignored: rows labelled '0-30' and '90+' have the same "
        "average shelf life left. See AGEING_BUCKET_NO_SIGNAL in /metrics/quality.",
    ]
    if risk.is_stale:
        notes.append(
            f"The stock position is {risk.snapshot_age_days} days old. Snapshots "
            f"land weekly, so treat these as leads rather than counts."
        )

    return ExpiryResponse(
        as_of=day.isoformat(), region=region,
        snapshot_date=(
            risk.snapshot_date.isoformat() if risk.snapshot_date else None),
        snapshot_age_days=risk.snapshot_age_days,
        is_stale=risk.is_stale,
        near_lines=risk.near_lines, near_cases=risk.near_cases,
        near_value_inr=risk.near_value_inr,
        doomed_lines=risk.doomed_lines, doomed_cases=risk.doomed_cases,
        doomed_value_inr=risk.doomed_value_inr,
        lines=[line.__dict__ for line in risk.lines],
        notes=notes,
    )


@router.get("/morning", response_model=MorningResponse)
def get_morning(
    as_of: str | None = Query(None, description="YYYY-MM-DD; omit for the "
                                                "last day with data"),
    region: str | None = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> MorningResponse:
    """Yesterday as a queue of things to do, each with an owner.

    The fill endpoints answer "how did the quarter go", which on frozen data is
    a constant and names no action. This answers the question Divya actually
    opens with: what broke, and who do I call about it.
    """
    try:
        day = morning_q.resolve_as_of(conn, as_of or settings.as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    region_id = _region_id(conn, region)
    payload = morning_q.morning(conn, day, region_id)
    handled.annotate(payload["events"], payload["as_of"])
    handled.annotate(payload["standing"], "standing")
    return MorningResponse(region=region, **payload)


def _as_of_key(value: str) -> str:
    if value == "standing":
        return value
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="as_of must be YYYY-MM-DD or 'standing'"
        ) from exc
    return value


@router.post("/morning/handle", response_model=HandleOut)
def handle_case(body: HandleIn) -> HandleOut:
    """Tick a case off the queue. Every screen reads the same file."""
    if not body.case_id.strip():
        raise HTTPException(status_code=400, detail="case_id is required")
    as_of = _as_of_key(body.as_of)
    handled.set_done(body.case_id.strip(), as_of, body.done)
    return HandleOut(case_id=body.case_id.strip(), as_of=as_of, done=body.done)
