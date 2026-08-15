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


class MorningResponse(BaseModel):
    as_of: str
    is_latest: bool
    region: str | None
    day: dict
    events: list[EventOut] = Field(
        description="What happened on this day. Empty is a valid answer."
    )
    standing: list[EventOut] = Field(
        description="Already true before the day started — a backlog, not fresh "
                    "damage. Kept apart so the two are never confused."
    )
    notes: list[str]
