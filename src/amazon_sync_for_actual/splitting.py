"""Plan per-item split transactions for matched Amazon orders.

When a single Actual transaction matches a multi-item order, we can split it into
one child subtransaction per item, each carrying that item's name as its note.
This is opt-in (``--split-mode items``) and pure here so it is fully testable
without ``actualpy``; the writer in :mod:`actual_sync` consumes the plan.

Per the project decision, splits are only produced when the item amounts are
**exact** -- i.e. the matched candidate's per-item ``total_cents`` sum to the
charge (within ``tolerance_cents``). Orders where item prices are unknown (e.g.
some browser-extension captures that only know the order total) are reported as
``not-exact`` and fall back to a single note elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from .matching import Match
from .memo import MemoOptions, format_item

__all__ = ["SplitChild", "SplitPlan", "plan_split", "plan_splits", "balance_amounts"]


@dataclass
class SplitChild:
    """One child subtransaction: a signed cent amount and its note."""

    amount_cents: int
    notes: str
    asin: Optional[str] = None


@dataclass
class SplitPlan:
    """A planned split (or a decision not to split) for one matched transaction."""

    txn: "object"                       # the TxnView being split
    children: List[SplitChild] = field(default_factory=list)
    action: str = "skip"                # split | skip-single | skip-already | not-exact | skip-existing-split
    reason: str = ""

    @property
    def changes(self) -> bool:
        return self.action == "split"


def balance_amounts(amounts: Sequence[int], target: int) -> List[int]:
    """Adjust *amounts* (cents) so they sum exactly to *target*.

    Any residual (from rounding) is applied to the largest-magnitude element, so
    children always reconcile to the parent to the cent. Assumes the inputs are
    already close to *target* (we only nudge by the residual).
    """
    amounts = list(amounts)
    if not amounts:
        return amounts
    residual = target - sum(amounts)
    if residual:
        # Apply to the entry with the largest magnitude (most able to absorb it).
        idx = max(range(len(amounts)), key=lambda i: abs(amounts[i]))
        amounts[idx] += residual
    return amounts


def plan_split(
    match: Match,
    memo_opts: Optional[MemoOptions] = None,
    *,
    tolerance_cents: int = 0,
    min_items: int = 2,
) -> SplitPlan:
    """Decide whether/how to split a single matched transaction per item."""
    memo_opts = memo_opts or MemoOptions()
    txn = match.txn
    items = [i for i in match.items if i and i.name and i.name.strip()]

    # Already a split parent in Actual? Leave it alone (idempotent / non-destructive).
    raw = getattr(txn, "raw", None)
    if raw is not None and (getattr(raw, "is_parent", 0) or getattr(raw, "isParent", 0)):
        return SplitPlan(txn, [], "skip-already", "transaction is already split")

    if len(items) < min_items:
        return SplitPlan(txn, [], "skip-single", "fewer than two items")

    # Exactness gate: every item must have a usable amount and the signed sum
    # must equal the charge within tolerance.
    charge = txn.amount_cents                       # negative for spending
    sign = -1 if charge < 0 else 1
    magnitudes = [int(i.total_cents) for i in items]
    if any(m <= 0 for m in magnitudes):
        return SplitPlan(txn, [], "not-exact", "one or more items have no price")
    diff = abs(sum(magnitudes) - abs(charge))
    if diff > tolerance_cents:
        return SplitPlan(
            txn, [], "not-exact",
            f"item total {sum(magnitudes)}c != charge {abs(charge)}c (diff {diff}c)",
        )

    # Build signed child amounts and force exact balance to the parent.
    signed = [sign * m for m in magnitudes]
    signed = balance_amounts(signed, charge)
    children = [
        SplitChild(amount_cents=amt, notes=format_item(item, memo_opts), asin=item.asin)
        for amt, item in zip(signed, items)
    ]
    return SplitPlan(txn, children, "split", "")


def plan_splits(
    matches: Sequence[Match],
    memo_opts: Optional[MemoOptions] = None,
    *,
    tolerance_cents: int = 0,
    min_items: int = 2,
) -> List[SplitPlan]:
    return [
        plan_split(m, memo_opts, tolerance_cents=tolerance_cents, min_items=min_items)
        for m in matches
    ]
