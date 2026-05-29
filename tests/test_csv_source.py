import io
import os
import zipfile
from datetime import date

from conftest import DATA

from amazon_sync_for_actual.sources.csv_source import CsvSource, rows_to_orders

RETAIL = os.path.join(DATA, "retail_order_history_sample.csv")
LEGACY = os.path.join(DATA, "legacy_items_sample.csv")


def _orders_by_id(orders):
    return {o.order_id: o for o in orders}


def test_retail_export_parsing():
    orders = _orders_by_id(CsvSource(RETAIL).fetch_orders())
    a = orders["112-1111111-1111111"]
    assert a.order_date == date(2024, 1, 10)
    assert a.total_cents == 1776 + 2600
    assert "Glad Tall Kitchen Drawstring Trash Bags OdorShield 13 Gallon" in a.item_names()

    b = orders["113-2222222-2222222"]
    assert b.total_cents == 1250 + 3000
    # two distinct ship dates -> two shipment groups
    assert len(b.shipments()) == 2
    batteries = next(i for i in b.items if "Batteries" in i.name)
    assert batteries.quantity == 2


def test_zero_dollar_digital_order_kept_but_zero():
    orders = _orders_by_id(CsvSource(RETAIL).fetch_orders())
    digital = orders["114-3333333-3333333"]
    assert digital.total_cents == 0


def test_legacy_items_report():
    orders = _orders_by_id(CsvSource(LEGACY).fetch_orders())
    widget = orders["222-1234567-7654321"]
    assert widget.order_date == date(2024, 1, 10)
    assert widget.total_cents == 1080  # "Item Total"
    assert widget.items[0].quantity == 2
    assert widget.items[0].name == "Widget Deluxe Edition"


def test_directory_source(tmp_path):
    # Copy the retail csv into a directory and read the directory.
    target = tmp_path / "Retail.OrderHistory.1.csv"
    target.write_text(open(RETAIL, encoding="utf-8").read(), encoding="utf-8")
    orders = CsvSource(str(tmp_path)).fetch_orders()
    assert any(o.order_id == "112-1111111-1111111" for o in orders)


def test_zip_source(tmp_path):
    archive = tmp_path / "amazon-data.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(RETAIL, "Retail.OrderHistory.1/Retail.OrderHistory.1.csv")
    orders = CsvSource(str(archive)).fetch_orders()
    assert any(o.order_id == "113-2222222-2222222" for o in orders)


def test_unit_price_fallback_when_total_missing():
    rows = [{"Order ID": "X", "Product Name": "Thing", "Unit Price": "5.00",
             "Unit Price Tax": "0.50", "Quantity": "2", "Order Date": "2024-01-01"}]
    orders = rows_to_orders(rows)
    assert orders[0].total_cents == (500 + 50) * 2


def test_missing_path_raises():
    try:
        CsvSource(None)
    except ValueError:
        return
    raise AssertionError("expected ValueError for missing path")
