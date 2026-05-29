import json
from datetime import date

from amazon_sync_for_actual.sources.json_source import JsonSource, orders_from_dicts


def test_orders_from_extension_camelcase():
    data = [
        {
            "orderId": "111-2222222-3333333",
            "orderDate": "2024-01-10",
            "orderTotalCents": 4376,
            "currency": "USD",
            "items": [
                {"name": "Trash Bags", "quantity": 1, "asin": "B00ABCDEFG"},
                {"name": "Mouthwash", "quantity": 2, "asin": "B00HIJKLMN"},
            ],
        }
    ]
    orders = orders_from_dicts(data)
    assert len(orders) == 1
    o = orders[0]
    assert o.order_id == "111-2222222-3333333"
    assert o.order_date == date(2024, 1, 10)
    assert o.total_cents == 4376              # override wins over summed items
    assert o.currency == "USD"
    assert [i.quantity for i in o.items] == [1, 2]


def test_orders_wrapped_and_snake_case_and_string_money():
    data = {"orders": [
        {"order_id": "X", "order_date": "2024-02-01", "order_total": "$12.50",
         "items": [{"title": "Batteries", "qty": "2", "total": "12.50"}]},
    ]}
    orders = orders_from_dicts(data)
    assert orders[0].order_id == "X"
    assert orders[0].total_cents == 1250
    assert orders[0].items[0].name == "Batteries"
    assert orders[0].items[0].quantity == 2


def test_empty_and_bad_input():
    assert orders_from_dicts([]) == []
    assert orders_from_dicts({"orders": []}) == []
    # rows that are not dicts are skipped
    assert orders_from_dicts([None, 5, "x"]) == []


def test_json_file_source(tmp_path):
    p = tmp_path / "orders.json"
    p.write_text(json.dumps([
        {"orderId": "A", "orderDate": "2024-03-01", "orderTotalCents": 999,
         "items": [{"name": "Thing", "quantity": 1}]}
    ]), encoding="utf-8")
    orders = JsonSource(str(p)).fetch_orders()
    assert orders[0].order_id == "A"
    assert orders[0].total_cents == 999


def test_build_source_dispatches_json_by_extension(tmp_path):
    from amazon_sync_for_actual.config import Config
    from amazon_sync_for_actual.sources import build_source

    p = tmp_path / "x.json"
    p.write_text("[]", encoding="utf-8")
    src = build_source(Config(source="csv", csv_path=str(p)))
    assert src.__class__.__name__ == "JsonSource"
