"""Arithmetic over quantity sums.

Deliberately free of SQL and of FastAPI. SQL hands these functions totals; they
turn totals into the numbers Divya and Rakesh argue about. Keeping the split
means the definitions can be tested by hand, without a 500k-row database.
"""

from dataclasses import dataclass

EPSILON = 1e-9


@dataclass(frozen=True)
class Sums:
    """Quantity totals for one set of order lines, in both units."""

    ordered_cases: float
    delivered_cases: float
    allocated_cases: float
    ordered_eaches: float
    delivered_eaches: float
    allocated_eaches: float
    case_only_ordered: float
    case_only_delivered: float
    case_only_lines_dropped: int
    orders: int
    lines: int

    @classmethod
    def zero(cls) -> "Sums":
        return cls(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0)


@dataclass(frozen=True)
class FillNumbers:
    case_pct: float | None
    each_pct: float | None
    case_only_pct: float | None
    case_only_lines_dropped: int


@dataclass(frozen=True)
class Service:
    execution_pct: float | None
    availability_pct: float | None
    service_pct: float | None
    identity_holds: bool


@dataclass(frozen=True)
class UnitsShort:
    shipped_short: float
    never_shipped: float
    total: float
    never_reserved: float
    reserved_not_sent: float


def pct(numerator: float, denominator: float) -> float | None:
    """Percentage, or None when there is nothing to divide.

    Returning None rather than 0.0 keeps "we have no data" distinguishable from
    "nothing arrived" — collapsing those is the kind of quiet lie this service
    exists to stop.
    """
    if denominator <= EPSILON:
        return None
    return 100.0 * numerator / denominator


def fill_numbers(attempted: Sums) -> FillNumbers:
    """The three fill rates, all computed from the same rows.

    case and each read every line and differ only in weighting. case_only
    filters to qty_uom='CASE' and silently discards the rest — it is computed
    so the API can show it is wrong, never as a default.
    """
    return FillNumbers(
        case_pct=pct(attempted.delivered_cases, attempted.ordered_cases),
        each_pct=pct(attempted.delivered_eaches, attempted.ordered_eaches),
        case_only_pct=pct(attempted.case_only_delivered, attempted.case_only_ordered),
        case_only_lines_dropped=attempted.case_only_lines_dropped,
    )


def decompose(attempted: Sums, refused: Sums) -> Service:
    """Split service into the two factors that multiply to produce it.

    execution     of what we tried to ship, how much arrived
    availability  of what they asked for, how much we agreed to ship

    The two have different owners — execution is the warehouse floor,
    availability is stock cover and credit policy. A single blended rate cannot
    say which one moved, which is precisely the problem this product exists to
    solve, so the layer never reports the blend alone.
    """
    execution = pct(attempted.delivered_cases, attempted.ordered_cases)
    asked = attempted.ordered_cases + refused.ordered_cases
    availability = pct(attempted.ordered_cases, asked)

    if execution is None or availability is None:
        return Service(execution, availability, None, True)

    service = execution * availability / 100.0
    blended = pct(attempted.delivered_cases, asked)
    holds = blended is not None and abs(service - blended) < 1e-9
    return Service(execution, availability, service, holds)


def units_short(attempted: Sums, refused: Sums) -> UnitsShort:
    """Missing units, split by cause.

    A count, not a rate: modern trade fines per missing unit, and unlike a
    percentage it does not swing with how many orders a shop happened to place.
    """
    shipped_short = attempted.ordered_eaches - attempted.delivered_eaches
    never_shipped = refused.ordered_eaches
    return UnitsShort(
        shipped_short=shipped_short,
        never_shipped=never_shipped,
        total=shipped_short + never_shipped,
        never_reserved=attempted.ordered_eaches - attempted.allocated_eaches,
        reserved_not_sent=attempted.allocated_eaches - attempted.delivered_eaches,
    )
