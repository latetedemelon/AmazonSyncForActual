"""Tolerant date parsing.

Amazon's various exports use different date formats depending on the source:
the GDPR "Request My Data" export uses ISO-8601 timestamps
(``2023-09-12T19:20:11Z``), the legacy order-history report uses ``MM/DD/YYYY``,
and invoice pages spell the month out (``September 12, 2023``).  We only ever
care about the calendar date, so this normalises all of them to
:class:`datetime.date`.
"""

from __future__ import annotations

import re
from datetime import date, datetime

__all__ = ["parse_date", "days_between"]

_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
)

_SPLIT = re.compile(r"[T ]")


def parse_date(value) -> date | None:
    """Parse *value* into a :class:`datetime.date`, or ``None`` if not possible."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    s = str(value).strip()
    if not s:
        return None

    # ISO-8601 first (most common in modern exports). ``fromisoformat`` on older
    # Pythons doesn't understand a trailing ``Z``.
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass

    # Fall back to the date portion before any time component.
    head = _SPLIT.split(s, maxsplit=1)[0]
    for candidate in (head, s):
        for fmt in _FORMATS:
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


def days_between(a: date | None, b: date | None) -> int | None:
    """Absolute number of days between two dates, or ``None`` if either is missing."""
    if a is None or b is None:
        return None
    return abs((a - b).days)
