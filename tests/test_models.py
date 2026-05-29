from datetime import date

from amazon_sync_for_actual.models import AmazonItem, AmazonOrder


def test_order_total_and_names():
    order = AmazonOrder(order_id="A", order_date=date(2024, 1, 1))
    order.add_item(AmazonItem(name="One", total_cents=100))
    order.add_item(AmazonItem(name="Two", total_cents=250))
    assert order.total_cents == 350
    assert order.item_names() == ["One", "Two"]


def test_total_override():
    order = AmazonOrder(order_id="A")
    order.add_item(AmazonItem(name="x", total_cents=0))
    order.add_item(AmazonItem(name="y", total_cents=0))
    assert order.total_cents == 0
    order.total_override_cents = 1599
    assert order.total_cents == 1599


def test_shipments_grouping():
    order = AmazonOrder(order_id="B")
    order.add_item(AmazonItem(name="a", total_cents=100, ship_date=date(2024, 1, 2)))
    order.add_item(AmazonItem(name="b", total_cents=200, ship_date=date(2024, 1, 5)))
    order.add_item(AmazonItem(name="c", total_cents=50, ship_date=date(2024, 1, 5)))
    groups = order.shipments()
    assert set(groups.keys()) == {date(2024, 1, 2), date(2024, 1, 5)}
    assert sum(i.total_cents for i in groups[date(2024, 1, 5)]) == 250
