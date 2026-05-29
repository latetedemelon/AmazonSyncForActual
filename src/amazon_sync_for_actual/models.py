"""Source-agnostic data model for Amazon orders.

Every ingestion source (CSV export, HTML scraping, ...) is responsible for
producing these plain dataclasses.  The matcher and memo builder only ever see
:class:`AmazonOrder` / :class:`AmazonItem`, which keeps the rest of the codebase
independent of where the data came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

__all__ = ["AmazonItem", "AmazonOrder"]


@dataclass
class AmazonItem:
    """A single line item within an order.

    ``total_cents`` is the *all-in* amount the customer was charged for this
    line (quantity * unit price, including allocated tax/shipping/discounts).
    That is what ultimately needs to reconcile against a card charge, so it is
    the canonical money field rather than unit price.
    """

    name: str
    quantity: int = 1
    total_cents: int = 0
    ship_date: Optional[date] = None
    asin: Optional[str] = None
    currency: str = "USD"


@dataclass
class AmazonOrder:
    """An Amazon order, i.e. all line items sharing one order id."""

    order_id: str
    order_date: Optional[date] = None
    items: List[AmazonItem] = field(default_factory=list)
    currency: str = "USD"

    @property
    def total_cents(self) -> int:
        """Sum of every line item's all-in total."""
        return sum(item.total_cents for item in self.items)

    def item_names(self) -> List[str]:
        return [item.name for item in self.items if item.name]

    def add_item(self, item: AmazonItem) -> None:
        self.items.append(item)
        if item.currency:
            self.currency = item.currency

    def shipments(self) -> "Dict[Optional[date], List[AmazonItem]]":
        """Group items by ship date.

        A single order can be split into multiple shipments that each become a
        separate card charge, so the matcher needs to be able to consider
        shipment subtotals as well as the order total.
        """
        groups: Dict[Optional[date], List[AmazonItem]] = {}
        for item in self.items:
            groups.setdefault(item.ship_date, []).append(item)
        return groups
