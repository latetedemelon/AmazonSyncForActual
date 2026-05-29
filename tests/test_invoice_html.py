import os
from datetime import date

import pytest

from conftest import DATA

bs4 = pytest.importorskip("bs4")  # invoice parsing needs beautifulsoup4

from amazon_sync_for_actual.sources.invoice_html import parse_invoice


def test_parse_invoice_sample():
    html = open(os.path.join(DATA, "invoice_simple.html"), encoding="utf-8").read()
    order = parse_invoice(html)
    assert order is not None
    assert order.order_id == "123-4567890-1234567"
    assert order.order_date == date(2024, 1, 10)
    names = order.item_names()
    assert "Widget A Premium Edition" in names
    assert "Gizmo Two Pack" in names
    # 18.00 before tax + 1.80 tax => 10% applied to each line total
    assert order.total_cents == 1100 + 880


def test_parse_invoice_no_items_returns_none():
    assert parse_invoice("<html><body>nothing here</body></html>") is None
