"""Read Amazon orders from JSON (the browser extension's structured output).

The extension can export the same orders it would write to CSV as JSON, and the
local bridge (`asfa serve`) receives that JSON over HTTP. This module turns that
structure into :class:`~amazon_sync_for_actual.models.AmazonOrder` objects.

Both camelCase (the extension's JS style) and snake_case keys are accepted, and
money may be given either as integer minor units (``*Cents``) or as a string
amount (``"43.76"``). It is pure and dependency-free, so it is fully testable.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base import AmazonSource
from ..dates import parse_date
from ..models import AmazonItem, AmazonOrder
from ..money import to_cents

__all__ = ["orders_from_dicts", "JsonSource"]


def _first(d: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in d and d[key] not in (None, ""):
            return d[key]
    return None


def _cents(d: Dict[str, Any], cents_keys, amount_keys) -> Optional[int]:
    """Resolve a money field given as integer cents or a string amount."""
    raw = _first(d, *cents_keys)
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return to_cents(raw)
    amount = _first(d, *amount_keys)
    return to_cents(amount) if amount is not None else None


def _item_from_dict(d: Dict[str, Any]) -> AmazonItem:
    quantity = _first(d, "quantity", "qty")
    try:
        quantity = max(1, int(quantity)) if quantity is not None else 1
    except (TypeError, ValueError):
        quantity = 1
    return AmazonItem(
        name=str(_first(d, "name", "title", "productName", "product_name") or "(unnamed item)"),
        quantity=quantity,
        total_cents=_cents(d, ("totalCents", "total_cents"), ("total", "totalOwed", "total_owed")) or 0,
        ship_date=parse_date(_first(d, "shipDate", "ship_date")),
        asin=_first(d, "asin", "ASIN"),
        currency=str(_first(d, "currency") or "USD"),
    )


def orders_from_dicts(data: Any) -> List[AmazonOrder]:
    """Convert a list of order dicts (or ``{"orders": [...]}``) into orders."""
    if isinstance(data, dict) and "orders" in data:
        data = data["orders"]
    if not isinstance(data, list):
        raise ValueError("Expected a JSON list of orders (or an object with 'orders').")

    orders: List[AmazonOrder] = []
    for i, raw in enumerate(data):
        if not isinstance(raw, dict):
            continue
        currency = str(_first(raw, "currency") or "USD")
        order = AmazonOrder(
            order_id=str(_first(raw, "orderId", "order_id", "id") or f"_no_order_{i}"),
            order_date=parse_date(_first(raw, "orderDate", "order_date", "date")),
            currency=currency,
        )
        override = _cents(
            raw,
            ("orderTotalCents", "order_total_cents", "totalCents", "total_cents"),
            ("orderTotal", "order_total", "total", "grandTotal", "grand_total"),
        )
        if override is not None:
            order.total_override_cents = override

        for item_dict in (raw.get("items") or []):
            if isinstance(item_dict, dict):
                order.add_item(_item_from_dict(item_dict))
        order.currency = currency  # add_item may have flipped it; keep order-level

        if order.items or order.total_override_cents is not None:
            orders.append(order)
    return orders


class JsonSource(AmazonSource):
    """Reads orders from a ``.json`` file produced by the extension."""

    def __init__(self, path: Optional[str]):
        if not path:
            raise ValueError("JsonSource requires a path to a JSON file.")
        self.path = path

    def fetch_orders(self) -> List[AmazonOrder]:
        with open(self.path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return orders_from_dicts(data)
