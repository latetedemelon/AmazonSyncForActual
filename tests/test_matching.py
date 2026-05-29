from datetime import date

from amazon_sync_for_actual.matching import TxnView, match_orders
from amazon_sync_for_actual.models import AmazonItem, AmazonOrder


def _order(order_id, when, *items):
    o = AmazonOrder(order_id=order_id, order_date=when)
    for item in items:
        o.add_item(item)
    return o


def test_simple_order_total_match():
    order = _order(
        "A", date(2024, 1, 10),
        AmazonItem(name="Trash Bags", total_cents=1776, ship_date=date(2024, 1, 11)),
        AmazonItem(name="Mouthwash", total_cents=2600, ship_date=date(2024, 1, 11)),
    )
    txn = TxnView(id=1, amount_cents=-4376, date=date(2024, 1, 12), payee_name="Amazon.com")
    result = match_orders([order], [txn])
    assert len(result.matches) == 1
    assert result.matches[0].order.order_id == "A"
    assert {i.name for i in result.matches[0].items} == {"Trash Bags", "Mouthwash"}
    assert not result.unmatched_txns


def test_shipment_level_split_charges():
    order = _order(
        "B", date(2024, 2, 1),
        AmazonItem(name="Batteries", total_cents=1250, ship_date=date(2024, 2, 2)),
        AmazonItem(name="Cable", total_cents=3000, ship_date=date(2024, 2, 5)),
    )
    t1 = TxnView(id=1, amount_cents=-1250, date=date(2024, 2, 3), payee_name="AMZN Mktp")
    t2 = TxnView(id=2, amount_cents=-3000, date=date(2024, 2, 6), payee_name="AMZN Mktp")
    result = match_orders([order], [t1, t2])
    matched = {m.txn.id: [i.name for i in m.items] for m in result.matches}
    assert matched == {1: ["Batteries"], 2: ["Cable"]}


def test_items_consumed_only_once():
    order = _order("A", date(2024, 1, 10), AmazonItem(name="Thing", total_cents=4376))
    t1 = TxnView(id=1, amount_cents=-4376, date=date(2024, 1, 10), payee_name="Amazon")
    t2 = TxnView(id=2, amount_cents=-4376, date=date(2024, 1, 10), payee_name="Amazon")
    result = match_orders([order], [t1, t2])
    assert len(result.matches) == 1
    assert len(result.unmatched_txns) == 1


def test_payee_filter_and_sign():
    order = _order("A", date(2024, 1, 10), AmazonItem(name="Thing", total_cents=500))
    not_amazon = TxnView(id=1, amount_cents=-500, date=date(2024, 1, 10), payee_name="Starbucks")
    positive = TxnView(id=2, amount_cents=500, date=date(2024, 1, 10), payee_name="Amazon")
    result = match_orders([order], [not_amazon, positive])
    assert not result.matches


def test_include_positive_refunds():
    order = _order("A", date(2024, 1, 10), AmazonItem(name="Thing", total_cents=500))
    refund = TxnView(id=2, amount_cents=500, date=date(2024, 1, 10), payee_name="Amazon")
    result = match_orders([order], [refund], include_positive=True)
    assert len(result.matches) == 1


def test_tolerance_cents():
    order = _order("A", date(2024, 1, 10), AmazonItem(name="Thing", total_cents=4376))
    txn = TxnView(id=1, amount_cents=-4377, date=date(2024, 1, 10), payee_name="Amazon")
    assert not match_orders([order], [txn]).matches
    assert match_orders([order], [txn], tolerance_cents=1).matches


def test_date_window():
    order = _order("A", date(2024, 1, 10), AmazonItem(name="Thing", total_cents=4376))
    far = TxnView(id=1, amount_cents=-4376, date=date(2024, 3, 1), payee_name="Amazon")
    assert not match_orders([order], [far], date_window_days=5).matches
    assert match_orders([order], [far], date_window_days=60).matches


def test_unmatched_orders_reported():
    order = _order("A", date(2024, 1, 10), AmazonItem(name="Thing", total_cents=999))
    txn = TxnView(id=1, amount_cents=-100, date=date(2024, 1, 10), payee_name="Amazon")
    result = match_orders([order], [txn])
    assert [o.order_id for o in result.unmatched_orders] == ["A"]
