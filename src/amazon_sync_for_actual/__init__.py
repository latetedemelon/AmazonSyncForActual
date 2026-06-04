"""Amazon Sync for Actual.

Enrich "Amazon.com" transactions in `Actual Budget <https://actualbudget.org>`_
with the itemized order details that Amazon normally hides, so historical
spending is actually categorizable.

The package is intentionally split so that the data-wrangling pieces (parsing
Amazon exports, building memos, matching orders to transactions) have **no**
heavy third-party dependencies and can be imported and unit-tested anywhere.
The integrations that *do* need optional dependencies -- ``actualpy`` for
talking to Actual and ``selenium`` for scraping Amazon -- import them lazily so
that importing this package never fails just because an optional extra is
missing.
"""

from __future__ import annotations

__version__ = "0.3.6"

from .models import AmazonItem, AmazonOrder
from .memo import MemoOptions, build_memo
from .matching import Match, MatchResult, TxnView, match_orders

__all__ = [
    "__version__",
    "AmazonItem",
    "AmazonOrder",
    "MemoOptions",
    "build_memo",
    "Match",
    "MatchResult",
    "TxnView",
    "match_orders",
]
