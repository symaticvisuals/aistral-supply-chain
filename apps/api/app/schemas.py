"""Response models.

Percentages are `float | None` throughout: None means "nothing to divide", which
is a different claim from 0% and must not be flattened into one.
"""

from pydantic import BaseModel, Field


class WindowOut(BaseModel):
    id: str
    label: str
    start: str
    end: str
    is_latest_complete: bool


class ScopeOut(BaseModel):
    id: str
    label: str
    counted_cancel_reasons: list[str]
    contested: list[str] = Field(
        description="Reasons in this scope that a reasonable person would argue "
                    "about. Named so the judgement is visible, not buried."
    )


class ServiceOut(BaseModel):
    execution_pct: float | None = Field(
        description="Of what we tried to ship, how much arrived. The warehouse floor."
    )
    availability_pct: float | None = Field(
        description="Of what they asked for, how much we agreed to ship. "
                    "Stock cover and credit policy."
    )
    service_pct: float | None = Field(
        description="execution x availability. Reported with both factors, never "
                    "alone: a blended number cannot say which one moved."
    )
    identity_holds: bool


class FillOut(BaseModel):
    case_pct: float | None
    each_pct: float | None
    case_only_pct: float | None = Field(
        description="qty_uom='CASE' only. Computed to show it is wrong, never a "
                    "default — it silently discards every EACH line."
    )
    case_only_lines_dropped: int


class UnitsShortOut(BaseModel):
    shipped_short: float
    never_shipped: float
    total: float
    never_reserved: float
    reserved_not_sent: float


class RungOut(BaseModel):
    scope_id: str
    label: str
    execution_pct: float | None
    availability_pct: float | None
    service_pct: float | None
    shipped_short: float
    never_shipped: float


class ExcludedOutlet(BaseModel):
    outlet_id: int
    outlet_name: str
    status: str
    is_deleted: int
    orders: int
    reason: str


class ReceiptOut(BaseModel):
    excluded_outlets: list[ExcludedOutlet]
    orders_excluded: dict[str, int]
    total_orders_excluded: int


class FillResponse(BaseModel):
    window: WindowOut
    region: str | None
    scope: ScopeOut
    orders_counted: int
    service: ServiceOut
    fill: FillOut
    units_short: UnitsShortOut
    ladder: list[RungOut]
    exclusions: ReceiptOut
    notes: list[str]


class OutletRowOut(BaseModel):
    outlet_id: int
    outlet_name: str
    city: str | None
    channel: str | None
    orders: int
    case_fill_pct: float | None
    each_fill_pct: float | None
    units_asked: float
    units_short: float


class OutletsResponse(BaseModel):
    window: WindowOut
    region: str | None
    scope: ScopeOut
    limit: int
    by_units_short: list[OutletRowOut]
    by_fill_pct: list[OutletRowOut]
    overlap: int = Field(
        description="How many outlets appear on both lists. Frequently zero — the "
                    "two orderings name different shops."
    )
    exposure: dict[str, float] = Field(
        description="Units short represented by each list, so the cost of picking "
                    "one ordering over the other is a number rather than an opinion."
    )
    notes: list[str]


class FindingOut(BaseModel):
    id: str
    severity: str
    statement: str
    evidence: dict
    affects: list[str]


class QualityResponse(BaseModel):
    checked_at_window: WindowOut
    findings: list[FindingOut]
    blocking: list[str]


class CreditNotesOut(BaseModel):
    settled_inr: float = Field(description="Approved. Money Kestrel has agreed to.")
    undecided_inr: float = Field(description="Pending. Nobody has ruled on these.")
    refused_inr: float = Field(description="Rejected. Raised against us, not paid.")
    exposed_inr: float = Field(description="Settled plus undecided — the bill if "
                                           "every open note is allowed.")
    raised_inr: float
    settled_n: int
    undecided_n: int
    refused_n: int


class CategoryRowOut(BaseModel):
    category: str
    settled_inr: float
    undecided_inr: float
    refused_inr: float
    notes_n: int


class PendingQueueOut(BaseModel):
    notes_n: int
    value_inr: float
    oldest_date: str | None
    oldest_days: int | None
    stale_n: int = Field(description="Undecided for more than a year.")
    stale_inr: float


class MoneyResponse(BaseModel):
    window: WindowOut
    region: str | None
    dispatch_inr: float = Field(
        description="Recomputed from delivered quantity. Not line_value_inr, which "
                    "prices what was ordered."
    )
    credit_notes: CreditNotesOut
    settled_pct: float | None
    exposed_pct: float | None
    raised_pct: float | None
    ratio_is_material: bool = Field(
        description="False when the percentage is too small to carry a decision. "
                    "The rupee amounts are the usable numbers in that case."
    )
    by_category: list[CategoryRowOut]
    pending_queue: PendingQueueOut
    above_mrp: dict | None = Field(
        default=None,
        description="Listings selling above the maximum price printed on the "
                    "pack. Counted, never ranked: the spread between "
                    "retailers is about two standard errors.",
    )
    notes: list[str]


class StockLineOut(BaseModel):
    warehouse: str
    product: str
    sku: str
    batch: str
    on_hand_cases: int
    days_left: int
    days_of_cover: float
    value_inr: float
    expiry_date: str
    cannot_sell: bool = Field(
        description="Days of cover exceed the days left. Arithmetic, not a worry."
    )
    shelf_city: str | None = Field(
        default=None,
        description="Which city's shelf the price below is from. Named rather "
                    "than assumed: a DC feeds more than its own metro.",
    )
    shelf_lowest_inr: float | None = Field(
        default=None,
        description="Deepest discount standing in that city, averaged over the "
                    "listing's own observations. Says whether a promotion has "
                    "room left; null where we do not scrape.",
    )
    shelf_vs_mrp_pct: float | None = None
    shelf_listings: int = 0


class ExpiryResponse(BaseModel):
    as_of: str
    region: str | None = Field(
        description="The warehouse's region. Stock sits in a DC, so that is the "
                    "only geography that means anything here — unlike every other "
                    "region filter, which means the shop's."
    )
    snapshot_date: str | None
    snapshot_age_days: int | None
    is_stale: bool
    near_lines: int
    near_cases: int
    near_value_inr: float
    doomed_lines: int
    doomed_cases: int
    doomed_value_inr: float
    doomed_priced: int = Field(
        default=0,
        description="How many of the lines that cannot sell through have a "
                    "shelf price. Stated so a mostly-blank column reads as "
                    "coverage rather than as a bug.",
    )
    doomed_total: int = 0
    price_age_days: int | None = None
    price_cities: list[str] = Field(default_factory=list)
    lines: list[StockLineOut]
    notes: list[str]


class HealthResponse(BaseModel):
    status: str
    service: str
    database: dict


class EventOut(BaseModel):
    kind: str
    severity: str
    headline: str
    owner: str = Field(description="Who can actually fix this before noon.")
    detail: str
    items: list[dict]
    population: int = Field(
        description="How many cases exist. items may be a shorter working set."
    )
    priority: str = Field(
        description="Worst case in this category: act | decide | pattern."
    )
    act_now: int = Field(description="Cases here that need doing this morning.")


class HandleIn(BaseModel):
    case_id: str
    as_of: str = Field(description="YYYY-MM-DD for a day case, or 'standing'.")
    done: bool


class HandleOut(BaseModel):
    case_id: str
    as_of: str
    done: bool


class MorningResponse(BaseModel):
    as_of: str
    is_latest: bool
    earliest: str
    latest: str
    region: str | None
    day: dict
    events: list[EventOut] = Field(
        description="What happened on this day. Empty is a valid answer. "
                    "Ordered by what this morning can still change."
    )
    standing: list[EventOut] = Field(
        description="Already true before the day started — a backlog, not fresh "
                    "damage. Kept apart so the two are never confused."
    )
    priorities: list[dict] = Field(
        description="The tiers and their labels, so the screen never hardcodes them."
    )
    notes: list[str]
