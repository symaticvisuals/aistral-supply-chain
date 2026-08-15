"""Which rows count, and a receipt for the ones that did not.

Divya's ninety-minute morning exists because four systems each applied a
different silent filter to the same orders. A metric layer that hides its own
filter recreates that problem with better fonts, so every exclusion here returns
both the SQL predicate and an auditable record of what it removed.
"""

import sqlite3
from dataclasses import dataclass, field

from app.metrics.windows import Window

# Orders we actually attempted to fulfil. Cancelled orders are exactly 0% filled;
# everything else sits near the mean, so this is the only real boundary in the
# data. Note DELIVERED does not mean "delivered in full" — see quality findings.
ATTEMPTED_STATUSES = ("DELIVERED", "PARTIAL")

# A cancellation Kestrel caused is a service failure: the shop asked, we said no.
# CR01_CREDIT is the contested member — a credit hold is finance's call, not the
# warehouse's, and Divya would reasonably refuse to wear it. It is worth 1.35 pts
# on its own, so it lives here as a name rather than a literal: flip this one
# tuple and the whole layer, ladder included, moves with it.
STOCKOUT_CANCEL = "CR03_NO_STOCK"
CREDIT_CANCEL = "CR01_CREDIT"
CONTESTED_CANCEL_REASONS = (CREDIT_CANCEL,)

# Not service failures: the shop was shut, or the order should never have existed.
# Counting a duplicate would inflate the denominator with demand nobody had.
NON_FAULT_CANCEL_REASONS = ("CR02_OUTLET_CLOSED", "CR04_DUPLICATE")

# Test and migration rows still live in the production outlet table. Matched by
# pattern rather than hardcoded id so this keeps working as data changes — and
# every match is listed by name in the receipt so a false positive is visible
# rather than silently swallowed.
TEST_OUTLET_PATTERNS = ("ZZ\\_%", "%TEST%", "%DO NOT USE%", "%DUMMY%", "%MIGRAT%")


@dataclass(frozen=True)
class Scope:
    id: str
    label: str
    counted_cancel_reasons: tuple[str, ...]

    @property
    def contested(self) -> tuple[str, ...]:
        return tuple(r for r in self.counted_cancel_reasons
                     if r in CONTESTED_CANCEL_REASONS)


SCOPES: dict[str, Scope] = {
    "attempted": Scope(
        "attempted", "Attempted orders only — cancellations excluded entirely", ()
    ),
    "stockout": Scope(
        "stockout", "Attempted, plus stockout cancellations", (STOCKOUT_CANCEL,)
    ),
    "kestrel_fault": Scope(
        "kestrel_fault",
        "Attempted, plus cancellations Kestrel caused (stockout and credit hold)",
        (STOCKOUT_CANCEL, CREDIT_CANCEL),
    ),
    "all_cancels": Scope(
        "all_cancels",
        "Attempted, plus every cancellation including closed outlets and duplicates",
        (STOCKOUT_CANCEL, CREDIT_CANCEL, *NON_FAULT_CANCEL_REASONS),
    ),
}

DEFAULT_SCOPE = "kestrel_fault"
LADDER_ORDER = ("attempted", "stockout", "kestrel_fault", "all_cancels")


class ScopeError(ValueError):
    """Unknown scope. We do not fall back to a default silently."""


def get_scope(scope_id: str | None) -> Scope:
    key = scope_id or DEFAULT_SCOPE
    if key not in SCOPES:
        raise ScopeError(
            f"Unknown scope {key!r}. Choose one of: {', '.join(SCOPES)}."
        )
    return SCOPES[key]


def _test_outlet_clause(alias: str = "ot") -> str:
    ors = " OR ".join(
        f"UPPER({alias}.outlet_name) LIKE '{p}' ESCAPE '\\'"
        for p in TEST_OUTLET_PATTERNS
    )
    return f"({ors})"


def outlet_filter(alias: str = "ot") -> str:
    """Real, trading shops only."""
    return (
        f"{alias}.status = 'ACTIVE' AND {alias}.is_deleted = 0 "
        f"AND NOT {_test_outlet_clause(alias)}"
    )


def attempted_filter(alias: str = "o") -> str:
    joined = ", ".join(f"'{s}'" for s in ATTEMPTED_STATUSES)
    return f"{alias}.order_status IN ({joined})"


def refused_filter(scope: Scope, alias: str = "o") -> str:
    """Cancellations this scope counts as a total miss. Never matches if empty."""
    if not scope.counted_cancel_reasons:
        return "1 = 0"
    joined = ", ".join(f"'{r}'" for r in scope.counted_cancel_reasons)
    return (
        f"{alias}.order_status = 'CANCELLED' "
        f"AND {alias}.cancelled_reason_code IN ({joined})"
    )


@dataclass
class Receipt:
    """What we removed, by name and by count."""

    excluded_outlets: list[dict] = field(default_factory=list)
    orders_excluded: dict[str, int] = field(default_factory=dict)

    @property
    def total_orders_excluded(self) -> int:
        return sum(self.orders_excluded.values())


def build_receipt(
    conn: sqlite3.Connection,
    window: Window,
    scope: Scope,
    region_id: int | None = None,
) -> Receipt:
    """Enumerate every row this scope drops, with counts, inside the window."""
    where_region = "AND o.region_id = ?" if region_id is not None else ""
    args: list[object] = [window.start.isoformat(), window.end.isoformat()]
    if region_id is not None:
        args.append(region_id)

    rows = conn.execute(
        f"""
        SELECT ot.outlet_id, ot.outlet_name, ot.status, ot.is_deleted,
               COUNT(o.order_id) AS orders,
               CASE
                 WHEN {_test_outlet_clause()} THEN 'test_or_migration_row'
                 WHEN ot.is_deleted = 1 THEN 'outlet_deleted'
                 ELSE 'outlet_' || LOWER(ot.status)
               END AS reason
          FROM outlets ot
          JOIN orders o ON o.outlet_id = ot.outlet_id
         WHERE o.order_date BETWEEN ? AND ? {where_region}
           AND NOT ({outlet_filter()})
         GROUP BY ot.outlet_id, ot.outlet_name, ot.status, ot.is_deleted, reason
         ORDER BY orders DESC, ot.outlet_id
        """,
        args,
    ).fetchall()

    receipt = Receipt(excluded_outlets=[dict(r) for r in rows])

    counted = set(scope.counted_cancel_reasons)
    status_rows = conn.execute(
        f"""
        SELECT o.order_status, o.cancelled_reason_code, COUNT(*) AS n
          FROM orders o
          JOIN outlets ot ON ot.outlet_id = o.outlet_id
         WHERE o.order_date BETWEEN ? AND ? {where_region}
           AND {outlet_filter()}
         GROUP BY o.order_status, o.cancelled_reason_code
        """,
        args,
    ).fetchall()

    for row in status_rows:
        status, reason = row["order_status"], row["cancelled_reason_code"]
        if status in ATTEMPTED_STATUSES:
            continue
        if status == "CANCELLED" and reason in counted:
            continue
        key = f"cancelled_{reason}" if status == "CANCELLED" else f"status_{status}"
        receipt.orders_excluded[key.lower()] = row["n"]

    for row in rows:
        key = f"outlet_{row['reason']}"
        prior = receipt.orders_excluded.get(key, 0)
        receipt.orders_excluded[key] = prior + row["orders"]

    return receipt
