"""Match Amazon orders to Actual transactions.

The original project tried to solve a subset-sum problem -- given one card
charge, figure out *which* items made it up.  That is fundamentally ambiguous.
With a real order export we already know each order's (and each shipment's)
total, so the robust approach is the reverse: take each Amazon transaction in
Actual and find the order or shipment whose total equals the charge and whose
date is close by.

The matcher is deliberately pure: it works on :class:`TxnView` adapters and
:class:`~amazon_sync_for_actual.models.AmazonOrder` objects with no knowledge of
``actualpy``, which makes the (tricky) matching logic fully unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, List, Optional, Sequence

from .dates import days_between
from .models import AmazonItem, AmazonOrder

__all__ = [
    "TxnView",
    "MatchCandidate",
    "Match",
    "MatchResult",
    "build_candidates",
    "match_orders",
]

DEFAULT_PAYEE_REGEX = r"amazon|amzn|am\.com|prime video|kindle|audible|whole foods|wholefds"
_UNKNOWN_DATE_PENALTY = 10_000


@dataclass
class TxnView:
    """A normalized view of an Actual transaction the matcher can reason about.

    ``amount_cents`` follows Actual's convention: spending is negative.
    ``raw`` carries the underlying object (e.g. an ``actualpy`` ``Transactions``)
    so the sync layer can write changes back after a match.
    """

    id: Any
    amount_cents: int
    date: Optional[date] = None
    notes: str = ""
    payee_name: str = ""
    raw: Any = None


@dataclass
class MatchCandidate:
    """One way an order could account for a charge (the whole order, or a shipment)."""

    order: AmazonOrder
    items: List[AmazonItem]
    amount_cents: int
    label: str  # "order" or "shipment"
    when: Optional[date] = None


@dataclass
class Match:
    txn: TxnView
    candidate: MatchCandidate

    @property
    def order(self) -> AmazonOrder:
        return self.candidate.order

    @property
    def items(self) -> List[AmazonItem]:
        return self.candidate.items


@dataclass
class MatchResult:
    matches: List[Match] = field(default_factory=list)
    unmatched_txns: List[TxnView] = field(default_factory=list)
    unmatched_orders: List[AmazonOrder] = field(default_factory=list)


def build_candidates(order: AmazonOrder, match_shipments: bool = True) -> List[MatchCandidate]:
    """Enumerate the ways *order* could reconcile against a charge.

    Always yields a whole-order candidate.  When the order shipped in more than
    one shipment, also yields a candidate per shipment so split charges match.
    """
    candidates = [
        MatchCandidate(
            order=order,
            items=list(order.items),
            amount_cents=order.total_cents,
            label="order",
            when=order.order_date,
        )
    ]
    if match_shipments:
        groups = order.shipments()
        if len(groups) > 1:
            for ship_date, items in groups.items():
                subtotal = sum(item.total_cents for item in items)
                candidates.append(
                    MatchCandidate(
                        order=order,
                        items=list(items),
                        amount_cents=subtotal,
                        label="shipment",
                        when=ship_date or order.order_date,
                    )
                )
    return candidates


def match_orders(
    orders: Sequence[AmazonOrder],
    txns: Sequence[TxnView],
    *,
    payee_regex: str = DEFAULT_PAYEE_REGEX,
    tolerance_cents: int = 0,
    date_window_days: int = 5,
    match_shipments: bool = True,
    include_positive: bool = False,
) -> MatchResult:
    """Greedily match Amazon transactions to order/shipment totals.

    Args:
        orders: Parsed Amazon orders.
        txns: Candidate Actual transactions.
        payee_regex: Case-insensitive regex; only transactions whose payee
            matches are considered Amazon charges.
        tolerance_cents: Allowed absolute difference between a charge and a
            candidate total (handles rounding/currency quirks).
        date_window_days: Maximum allowed gap between the transaction date and
            the order/shipment date.
        match_shipments: Also consider per-shipment subtotals, not just order
            totals.
        include_positive: If ``True`` also match positive amounts (refunds).

    A candidate's items are "consumed" once matched, so the same physical items
    are never attributed to two different transactions.  Matching a shipment
    leaves the order's other shipments available; matching the whole order
    consumes everything.
    """
    pattern = re.compile(payee_regex, re.IGNORECASE)

    candidates: List[MatchCandidate] = []
    for order in orders:
        candidates.extend(build_candidates(order, match_shipments=match_shipments))

    amazon_txns = [t for t in txns if t.payee_name and pattern.search(t.payee_name)]
    if not include_positive:
        amazon_txns = [t for t in amazon_txns if t.amount_cents < 0]

    # Deterministic order: oldest first, ties broken by id.
    amazon_txns.sort(key=lambda t: (t.date or date.max, str(t.id)))

    consumed_item_ids: set = set()
    matches: List[Match] = []
    matched_txn_ids: set = set()

    for txn in amazon_txns:
        target = abs(txn.amount_cents)
        best: Optional[MatchCandidate] = None
        best_score: Optional[tuple] = None

        for cand in candidates:
            if cand.amount_cents <= 0:
                continue
            if any(id(item) in consumed_item_ids for item in cand.items):
                continue
            amount_diff = abs(cand.amount_cents - target)
            if amount_diff > tolerance_cents:
                continue

            gap = days_between(cand.when, txn.date)
            if gap is None:
                gap = _UNKNOWN_DATE_PENALTY  # unknown date: allow, but disfavor
            elif gap > date_window_days:
                continue

            label_rank = 0 if cand.label == "order" else 1
            score = (amount_diff, gap, label_rank, -len(cand.items))
            if best_score is None or score < best_score:
                best, best_score = cand, score

        if best is not None:
            for item in best.items:
                consumed_item_ids.add(id(item))
            matches.append(Match(txn=txn, candidate=best))
            matched_txn_ids.add(txn.id)

    unmatched_txns = [t for t in amazon_txns if t.id not in matched_txn_ids]
    matched_order_ids = {m.order.order_id for m in matches}
    unmatched_orders = [o for o in orders if o.order_id not in matched_order_ids]

    return MatchResult(
        matches=matches,
        unmatched_txns=unmatched_txns,
        unmatched_orders=unmatched_orders,
    )
