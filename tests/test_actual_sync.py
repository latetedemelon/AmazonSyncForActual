"""Tests for the planning layer.

Importing ``actual_sync`` must NOT require the optional ``actualpy`` package --
these tests run with it absent, which proves the lazy import works.
"""

from datetime import date

from amazon_sync_for_actual.actual_sync import ActualSyncer, SyncResult, plan_updates
from amazon_sync_for_actual.config import Config
from amazon_sync_for_actual.matching import TxnView, match_orders
from amazon_sync_for_actual.memo import MemoOptions
from amazon_sync_for_actual.models import AmazonItem, AmazonOrder


def _single_match(notes=""):
    order = AmazonOrder(order_id="A", order_date=date(2024, 1, 10))
    order.add_item(AmazonItem(name="Trash Bags", total_cents=4376))
    txn = TxnView(id=1, amount_cents=-4376, date=date(2024, 1, 11),
                  payee_name="Amazon", notes=notes)
    result = match_orders([order], [txn])
    assert result.matches
    return result.matches


def test_fill_writes_when_empty():
    updates = plan_updates(_single_match(notes=""), MemoOptions())
    assert updates[0].action == "write"
    assert updates[0].new_notes == "Trash Bags"


def test_fill_keeps_existing_user_note():
    updates = plan_updates(_single_match(notes="my own note"), MemoOptions())
    assert updates[0].action == "skip-existing"
    assert updates[0].new_notes == "my own note"


def test_fill_idempotent():
    updates = plan_updates(_single_match(notes="Trash Bags"), MemoOptions())
    assert updates[0].action == "skip-idempotent"


def test_append_mode():
    updates = plan_updates(_single_match(notes="prior"), MemoOptions(), note_mode="append")
    assert updates[0].action == "append"
    assert updates[0].new_notes == "prior | Trash Bags"
    # Running again is idempotent.
    again = plan_updates(_single_match(notes="prior | Trash Bags"), MemoOptions(),
                         note_mode="append")
    assert again[0].action == "skip-idempotent"


def test_prepend_mode():
    updates = plan_updates(_single_match(notes="prior"), MemoOptions(), note_mode="prepend")
    assert updates[0].action == "prepend"
    assert updates[0].new_notes == "Trash Bags | prior"
    # Writes into an empty note like a plain write.
    empty = plan_updates(_single_match(notes=""), MemoOptions(), note_mode="prepend")
    assert empty[0].action == "write"
    assert empty[0].new_notes == "Trash Bags"
    # Running again is idempotent (memo already present).
    again = plan_updates(_single_match(notes="Trash Bags | prior"), MemoOptions(),
                         note_mode="prepend")
    assert again[0].action == "skip-idempotent"


def test_overwrite_mode():
    updates = plan_updates(_single_match(notes="prior"), MemoOptions(), note_mode="overwrite")
    assert updates[0].action == "write"
    assert updates[0].new_notes == "Trash Bags"


def test_syncer_plan_end_to_end():
    order = AmazonOrder(order_id="A", order_date=date(2024, 1, 10))
    order.add_item(AmazonItem(name="Widget", total_cents=1000))
    order.add_item(AmazonItem(name="Gadget", total_cents=500))
    txns = [
        TxnView(id=1, amount_cents=-1500, date=date(2024, 1, 11), payee_name="Amazon.com"),
        TxnView(id=2, amount_cents=-999, date=date(2024, 1, 11), payee_name="Starbucks"),
    ]
    result = ActualSyncer(Config())._plan([order], txns)
    assert isinstance(result, SyncResult)
    changed = result.changed
    assert len(changed) == 1
    assert changed[0].txn.id == 1
    assert "Widget" in changed[0].new_notes and "Gadget" in changed[0].new_notes
