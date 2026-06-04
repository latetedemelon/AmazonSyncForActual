"""Read Amazon orders from a CSV export.

This is the recommended source: it is deterministic, needs no login automation
and does not fight Amazon's bot defenses.  Get the data from
``Account > Privacy Central > Request My Data > "Your Orders"`` (or the legacy
order-history report).  Amazon delivers a ZIP whose useful file is
``Retail.OrderHistory.1/Retail.OrderHistory.1.csv``.

The reader accepts a single ``.csv`` file, a directory (it finds the relevant
CSVs), or the raw ``.zip`` download, and tolerates header differences between the
modern export and the older "Items"/"Orders" reports via an alias table.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import zipfile
from typing import Dict, List, Optional

from .base import AmazonSource
from ..dates import parse_date
from ..models import AmazonItem, AmazonOrder
from ..money import to_cents

log = logging.getLogger(__name__)

__all__ = ["CsvSource", "rows_to_orders"]

# Canonical field <- possible header spellings (compared lower-cased & stripped).
_FIELD_ALIASES: Dict[str, str] = {
    "order id": "order_id",
    "order_id": "order_id",
    "website order id": "order_id",
    "order date": "order_date",
    "ship date": "ship_date",
    "shipment date": "ship_date",
    "product name": "name",
    "title": "name",
    "item name": "name",
    "quantity": "quantity",
    "qty": "quantity",
    "total owed": "total_owed",
    "item total": "total_owed",
    "order total": "order_total",
    "grand total": "order_total",
    "total charged": "order_total",
    "unit price": "unit_price",
    "purchase price per unit": "unit_price",
    "unit price tax": "unit_price_tax",
    "currency": "currency",
    "asin": "asin",
    "asin/isbn": "asin",
}

# Filenames we recognise inside a directory / zip, in priority order.
_KNOWN_CSV_HINTS = (
    "retail.orderhistory",
    "order history",
    "orderhistory",
    "items",
    "orders",
)


def _canonical_row(row: Dict[str, str]) -> Dict[str, str]:
    """Map a raw CSV row's headers onto our canonical field names."""
    canonical: Dict[str, str] = {}
    for header, value in row.items():
        if header is None:
            continue
        key = _FIELD_ALIASES.get(header.strip().lower())
        if key and (key not in canonical or not canonical[key]):
            canonical[key] = (value or "").strip()
    return canonical


def _parse_quantity(value: Optional[str]) -> int:
    if not value:
        return 1
    try:
        return max(1, int(float(value)))
    except (TypeError, ValueError):
        return 1


def _line_total_cents(canonical: Dict[str, str]) -> int:
    """Best-effort all-in total for one CSV line, in cents."""
    total = to_cents(canonical.get("total_owed"))
    if total is not None:
        return total
    # Fall back to unit price (* quantity) + per-unit tax.
    unit = to_cents(canonical.get("unit_price"))
    if unit is None:
        return 0
    qty = _parse_quantity(canonical.get("quantity"))
    tax = to_cents(canonical.get("unit_price_tax")) or 0
    return (unit + tax) * qty


def rows_to_orders(rows: List[Dict[str, str]]) -> List[AmazonOrder]:
    """Group raw CSV rows into :class:`AmazonOrder` objects."""
    orders: "Dict[str, AmazonOrder]" = {}
    order_sequence: List[str] = []

    for raw in rows:
        canonical = _canonical_row(raw)
        name = canonical.get("name", "")
        total = _line_total_cents(canonical)
        order_total = to_cents(canonical.get("order_total"))
        # Skip rows with no item and no money signal (blank lines, repeated
        # headers in concatenated files, etc.).
        if not name and total == 0 and order_total is None:
            continue

        order_id = canonical.get("order_id") or f"_no_order_{len(order_sequence)}"
        currency = canonical.get("currency") or "USD"
        order_date = parse_date(canonical.get("order_date"))
        ship_date = parse_date(canonical.get("ship_date"))

        if order_id not in orders:
            orders[order_id] = AmazonOrder(
                order_id=order_id, order_date=order_date, currency=currency
            )
            order_sequence.append(order_id)
        order = orders[order_id]
        if order.order_date is None and order_date is not None:
            order.order_date = order_date
        # An explicit order grand total (e.g. from the browser extension) wins
        # over summing per-item totals, which may be unavailable.
        if order_total is not None:
            order.total_override_cents = order_total

        if name or total:
            order.add_item(
                AmazonItem(
                    name=name or "(unnamed item)",
                    quantity=_parse_quantity(canonical.get("quantity")),
                    total_cents=total,
                    ship_date=ship_date,
                    asin=canonical.get("asin") or None,
                    currency=currency,
                )
            )

    # Drop only clear junk: a synthetic-id order (the source gave no order id)
    # that also has no money. These are $0 rows with nothing to reconcile. Real
    # $0-total orders (e.g. a purchase whose total didn't extract, or a digital
    # item) are kept — they can't match a charge but shouldn't be silently lost.
    return [
        orders[oid]
        for oid in order_sequence
        if not (oid.startswith("_no_order_") and orders[oid].total_cents == 0)
    ]


def _read_csv_text(text: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _looks_like_order_csv(name: str) -> bool:
    lower = os.path.basename(name).lower()
    if not lower.endswith(".csv"):
        return False
    return any(hint in lower for hint in _KNOWN_CSV_HINTS)


class CsvSource(AmazonSource):
    """Reads orders from a CSV file, a directory of CSVs, or the export ZIP."""

    def __init__(self, path: Optional[str]):
        if not path:
            raise ValueError("CsvSource requires a path to a CSV file, directory or ZIP.")
        self.path = path

    def fetch_orders(self) -> List[AmazonOrder]:
        rows = self._read_rows()
        orders = rows_to_orders(rows)
        log.info("Parsed %d order(s) from %s", len(orders), self.path)
        return orders

    # -- input handling ----------------------------------------------------
    def _read_rows(self) -> List[Dict[str, str]]:
        path = self.path
        if not os.path.exists(path):
            raise FileNotFoundError(f"CSV path does not exist: {path}")
        if os.path.isdir(path):
            return self._read_dir(path)
        if zipfile.is_zipfile(path):
            return self._read_zip(path)
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            return _read_csv_text(handle.read())

    def _read_dir(self, directory: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        matched: List[str] = []
        all_csvs: List[str] = []
        for root, _dirs, files in os.walk(directory):
            for fname in sorted(files):
                full = os.path.join(root, fname)
                if fname.lower().endswith(".csv"):
                    all_csvs.append(full)
                    if _looks_like_order_csv(fname):
                        matched.append(full)
        targets = matched or all_csvs  # fall back to every csv if names are unfamiliar
        if not targets:
            raise FileNotFoundError(f"No CSV files found under directory: {directory}")
        for full in targets:
            with open(full, "r", encoding="utf-8-sig", newline="") as handle:
                rows.extend(_read_csv_text(handle.read()))
        return rows

    def _read_zip(self, archive: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        with zipfile.ZipFile(archive) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            matched = [n for n in names if _looks_like_order_csv(n)]
            targets = matched or names
            if not targets:
                raise FileNotFoundError(f"No CSV files found inside ZIP: {archive}")
            for name in targets:
                with zf.open(name) as raw:
                    text = io.TextIOWrapper(raw, encoding="utf-8-sig").read()
                rows.extend(_read_csv_text(text))
        return rows
