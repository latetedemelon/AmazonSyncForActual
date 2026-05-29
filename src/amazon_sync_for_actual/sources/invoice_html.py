"""Parse an Amazon order *invoice/print* page into an :class:`AmazonOrder`.

This is a modernized, defensive port of the original project's ``parser.py``.
Amazon's invoice markup is notoriously unstable, so this is best-effort and used
only by the experimental Selenium source; the CSV source is far more reliable.

``beautifulsoup4`` is imported lazily so importing this module never requires it.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from ..dates import parse_date
from ..models import AmazonItem, AmazonOrder

log = logging.getLogger(__name__)

__all__ = ["parse_invoice"]

_ORDER_PLACED = re.compile(r"Order Placed:\s*(.+)", re.IGNORECASE)
_ORDER_NUMBER = re.compile(r"order number:\s*([0-9-]+)", re.IGNORECASE)
_LEADING_INT = re.compile(r"^\s*(\d+)")


def _money_to_cents(text: str) -> Optional[int]:
    from ..money import to_cents

    return to_cents(text)


def _find_amount_after(soup, label_regex: str) -> Optional[int]:
    """Find a ``$`` amount in the second table cell of a labelled row."""
    node = soup.find(string=re.compile(label_regex, re.IGNORECASE))
    if node is None:
        return None
    try:
        cells = node.parent.parent.find_all("td")
        return _money_to_cents(cells[1].get_text())
    except (AttributeError, IndexError):
        return None


def parse_invoice(html: str, order_id: Optional[str] = None) -> Optional[AmazonOrder]:
    """Parse invoice *html* into an order, or ``None`` if it can't be understood."""
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Parsing Amazon invoice HTML requires beautifulsoup4. Install the "
            "selenium extra: `pip install amazon-sync-for-actual[selenium]`."
        ) from exc

    soup = BeautifulSoup(html, "html.parser")

    # Item names appear in italics on the invoice (the original "dirty hack").
    raw_items: List[tuple] = []
    for italic in soup.find_all("i"):
        try:
            name = italic.get_text().strip()
            if not name:
                continue
            qty_match = _LEADING_INT.match(italic.parent.get_text())
            quantity = int(qty_match.group(1)) if qty_match else 1
            price_cells = italic.parent.parent.find_all("td")
            unit_cents = _money_to_cents(price_cells[1].get_text())
            if unit_cents is None:
                continue
            raw_items.append((name, quantity, unit_cents * quantity))
        except (AttributeError, IndexError, ValueError):
            continue

    if not raw_items:
        log.debug("No items found on invoice page for order %s", order_id)
        return None

    before_tax = _find_amount_after(soup, r"Total before tax")
    tax = _find_amount_after(soup, r"Estimated tax to be collected")
    tax_ratio = (tax / before_tax) if (before_tax and tax is not None and before_tax > 0) else 0.0

    order_date = None
    placed = soup.find(string=_ORDER_PLACED)
    if placed:
        m = _ORDER_PLACED.search(str(placed))
        if m:
            order_date = parse_date(m.group(1).strip())

    if order_id is None:
        num = soup.find(string=_ORDER_NUMBER)
        if num:
            m = _ORDER_NUMBER.search(str(num))
            if m:
                order_id = m.group(1).strip()

    order = AmazonOrder(order_id=order_id or "unknown", order_date=order_date)
    for name, quantity, line_cents in raw_items:
        after_tax = int(round(line_cents * (1 + tax_ratio)))
        order.add_item(AmazonItem(name=name, quantity=quantity, total_cents=after_tax))
    return order
