"""The extension's CSV export must flow straight into the importer + matcher.

This guards the contract between the browser extension (which writes the CSV) and
the Python tool (which reads it), using a committed sample identical to the
extension's output for amazon.com (USD) and amazon.co.uk (GBP).
"""

import os
from datetime import date

from conftest import DATA

from amazon_sync_for_actual.matching import TxnView, match_orders
from amazon_sync_for_actual.sources.csv_source import CsvSource

SAMPLE = os.path.join(DATA, "extension_export_sample.csv")


def _by_id(orders):
    return {o.order_id: o for o in orders}


def test_extension_csv_parses_all_marketplaces():
    orders = _by_id(CsvSource(SAMPLE).fetch_orders())
    assert set(orders) == {
        "111-2222222-3333333", "114-5555555-6666666", "203-1234567-7654321"
    }

    us = orders["111-2222222-3333333"]
    assert us.currency == "USD"
    assert us.order_date == date(2024, 1, 10)
    assert us.total_cents == 4376          # from Order Total, not summed items
    assert len(us.items) == 2

    uk = orders["203-1234567-7654321"]
    assert uk.currency == "GBP"
    assert uk.total_cents == 2999
    assert uk.items[0].quantity == 1


def test_extension_csv_matches_transactions():
    orders = CsvSource(SAMPLE).fetch_orders()
    txns = [
        TxnView(id="t-us", amount_cents=-4376, date=date(2024, 1, 11), payee_name="Amazon.com"),
        TxnView(id="t-uk", amount_cents=-2999, date=date(2024, 1, 13), payee_name="AMZN Mktp UK"),
        TxnView(id="t-aaa", amount_cents=-1250, date=date(2024, 2, 3), payee_name="Amazon.com"),
    ]
    result = match_orders(orders, txns)
    matched = {m.txn.id: m.order.order_id for m in result.matches}
    assert matched == {
        "t-us": "111-2222222-3333333",
        "t-uk": "203-1234567-7654321",
        "t-aaa": "114-5555555-6666666",
    }
    assert not result.unmatched_txns
