"""Money parsing helpers.

Amazon exports money as messy strings (``"$1,234.56"``, ``"USD 12.34"``,
``"(5.00)"`` for credits, or just ``""``).  Actual stores money as an integer
number of minor units (cents for USD).  Everything in this project works in
integer cents to avoid floating-point drift, so this module is the single place
that turns human strings into cents.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

__all__ = ["parse_decimal", "to_cents", "cents_to_str"]

# Strip anything that is not a digit, separator or sign.  Currency symbols,
# letters (``USD``) and stray whitespace all go.
_NON_NUMERIC = re.compile(r"[^0-9.,\-]")


def parse_decimal(value) -> Decimal | None:
    """Parse a loosely-formatted money value into a :class:`~decimal.Decimal`.

    Returns ``None`` when *value* is empty or cannot be interpreted as a number.
    Handles thousands separators, comma decimals (``"12,34"``), parenthesised
    negatives (``"(5.00)"``) and surrounding currency text.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # avoid treating True/False as 1/0
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    s = str(value).strip()
    if not s:
        return None

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]

    s = _NON_NUMERIC.sub("", s)
    if s.count("-") > 1:  # e.g. a stray range like "1-2"
        return None
    if s.startswith("-"):
        negative = not negative
        s = s[1:]
    if not s or s in {".", ","}:
        return None

    # Reconcile thousands vs decimal separators.
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            # European style: 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        # A single comma with 1-2 trailing digits is a decimal comma.
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")

    try:
        result = Decimal(s)
    except InvalidOperation:
        return None
    return -result if negative else result


def to_cents(value) -> int | None:
    """Parse *value* and return integer minor units (cents), or ``None``."""
    parsed = parse_decimal(value)
    if parsed is None:
        return None
    return int((parsed * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cents_to_str(cents: int, currency: str = "") -> str:
    """Render integer cents as a human ``"-12.34"`` style string."""
    sign = "-" if cents < 0 else ""
    magnitude = abs(int(cents))
    body = f"{magnitude // 100}.{magnitude % 100:02d}"
    return f"{currency}{sign}{body}" if currency else f"{sign}{body}"
