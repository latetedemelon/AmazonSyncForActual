"""Apply matched Amazon order details to Actual Budget transactions.

This module has two layers:

* :func:`plan_updates` is pure -- given matches and memo options it decides what
  each transaction's note *should* become and whether that is a change.  It is
  fully unit-testable without ``actualpy``.
* :class:`ActualSyncer` connects to a real Actual server (importing ``actualpy``
  lazily), reads transactions, runs the matcher + planner, writes the notes back
  and commits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from .config import Config
from .matching import Match, MatchResult, TxnView, match_orders
from .memo import MemoOptions, build_memo
from .models import AmazonOrder

log = logging.getLogger(__name__)

__all__ = ["Update", "SyncResult", "plan_updates", "ActualSyncer", "CHANGING_ACTIONS"]

# Actions that represent an actual write to the transaction.
CHANGING_ACTIONS = {"write", "append", "prepend"}


@dataclass
class Update:
    """A planned change (or non-change) to a single transaction's note."""

    txn: TxnView
    memo: str          # the freshly generated item memo
    new_notes: str     # what the note field would become
    action: str        # write | append | skip-existing | skip-idempotent | empty-memo

    @property
    def changes(self) -> bool:
        return self.action in CHANGING_ACTIONS


@dataclass
class SyncResult:
    updates: List[Update] = field(default_factory=list)
    unmatched_txns: List[TxnView] = field(default_factory=list)
    unmatched_orders: List[AmazonOrder] = field(default_factory=list)
    committed: bool = False

    @property
    def changed(self) -> List[Update]:
        return [u for u in self.updates if u.changes]

    def summary(self) -> str:
        writes = sum(1 for u in self.updates if u.action == "write")
        appends = sum(1 for u in self.updates if u.action == "append")
        prepends = sum(1 for u in self.updates if u.action == "prepend")
        skipped = len(self.updates) - writes - appends - prepends
        return (
            f"matched={len(self.updates)} "
            f"write={writes} prepend={prepends} append={appends} skipped={skipped} "
            f"unmatched_txns={len(self.unmatched_txns)} "
            f"unmatched_orders={len(self.unmatched_orders)} "
            f"committed={self.committed}"
        )


def plan_updates(
    matches: Sequence[Match],
    memo_opts: Optional[MemoOptions] = None,
    note_mode: str = "fill",
) -> List[Update]:
    """Decide the new note for each match according to *note_mode*.

    ``fill``      only writes when the note is currently empty (safe default).
    ``prepend``   inserts the memo before any existing note.
    ``append``    adds the memo after any existing note (postpend).
    ``overwrite`` replaces the note entirely.

    Every mode is idempotent: re-running never produces a duplicate change.
    """
    memo_opts = memo_opts or MemoOptions()
    updates: List[Update] = []

    for match in matches:
        memo = build_memo(match.items, memo_opts)
        existing = match.txn.notes or ""

        if not memo:
            updates.append(Update(match.txn, memo, existing, "empty-memo"))
            continue

        if note_mode == "overwrite":
            action = "skip-idempotent" if existing == memo else "write"
            new_notes = existing if action == "skip-idempotent" else memo
        elif note_mode == "prepend":
            if memo in existing:
                action, new_notes = "skip-idempotent", existing
            elif not existing:
                action, new_notes = "write", memo
            else:
                action, new_notes = "prepend", memo + memo_opts.separator + existing
        elif note_mode == "append":
            if memo in existing:
                action, new_notes = "skip-idempotent", existing
            elif not existing:
                action, new_notes = "write", memo
            else:
                action, new_notes = "append", existing + memo_opts.separator + memo
        else:  # fill
            if not existing:
                action, new_notes = "write", memo
            elif existing == memo:
                action, new_notes = "skip-idempotent", existing
            else:
                action, new_notes = "skip-existing", existing

        updates.append(Update(match.txn, memo, new_notes, action))

    return updates


class ActualSyncer:
    """Connects to Actual, matches orders to transactions and writes notes."""

    def __init__(self, config: Config):
        self.config = config

    def _txn_to_view(self, txn) -> TxnView:
        payee_name = ""
        payee = getattr(txn, "payee", None)
        if payee is not None and getattr(payee, "name", None):
            payee_name = payee.name
        if not payee_name:
            payee_name = getattr(txn, "imported_description", "") or ""
        return TxnView(
            id=txn.id,
            amount_cents=int(txn.amount or 0),
            date=txn.get_date(),
            notes=txn.notes or "",
            payee_name=payee_name,
            raw=txn,
        )

    def run(self, orders: Sequence[AmazonOrder]) -> SyncResult:
        """Connect to Actual, plan updates and (unless dry-run) commit them."""
        try:
            from actual import Actual
            from actual.queries import get_transactions
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            raise RuntimeError(
                "The 'actualpy' package is required to talk to Actual. "
                "Install it with `pip install actualpy` (or `pip install "
                "amazon-sync-for-actual`)."
            ) from exc

        cfg = self.config
        start, end = cfg.date_range()
        log.info("Connecting to Actual at %s (file=%s)", cfg.actual_url, cfg.actual_file)

        with Actual(
            base_url=cfg.actual_url,
            password=cfg.actual_password,
            token=cfg.actual_token,
            file=cfg.actual_file,
            encryption_password=cfg.actual_encryption_password,
            cert=cfg.actual_cert,
        ) as actual:
            kwargs = {"start_date": start, "end_date": end}
            if cfg.account:
                kwargs["account"] = cfg.account
            raw_txns = get_transactions(actual.session, **kwargs)
            txns = [self._txn_to_view(t) for t in raw_txns]
            log.info("Fetched %d transactions between %s and %s", len(txns), start, end)

            result = self._plan(orders, txns)

            if result.changed and not cfg.dry_run:
                for update in result.changed:
                    update.txn.raw.notes = update.new_notes
                actual.commit()
                result.committed = True
                log.info("Committed %d note update(s) to Actual", len(result.changed))
            elif cfg.dry_run:
                log.info("Dry-run: %d change(s) NOT written", len(result.changed))

        return result

    def _plan(self, orders: Sequence[AmazonOrder], txns: Sequence[TxnView]) -> SyncResult:
        """The Actual-independent core of :meth:`run` (handy for testing)."""
        cfg = self.config
        match_result: MatchResult = match_orders(
            orders,
            txns,
            payee_regex=cfg.payee_regex,
            tolerance_cents=cfg.tolerance_cents,
            date_window_days=cfg.date_window_days,
            match_shipments=cfg.match_shipments,
            include_positive=cfg.include_positive,
        )
        updates = plan_updates(match_result.matches, cfg.memo_options(), cfg.note_mode)
        return SyncResult(
            updates=updates,
            unmatched_txns=match_result.unmatched_txns,
            unmatched_orders=match_result.unmatched_orders,
        )
