from datetime import date

from amazon_sync_for_actual.matching import TxnView, match_orders
from amazon_sync_for_actual.memo import MemoOptions
from amazon_sync_for_actual.models import AmazonItem, AmazonOrder
from amazon_sync_for_actual.splitting import balance_amounts, plan_split, plan_splits


def _match(notes="", *, items, charge_cents, raw=None):
    order = AmazonOrder(order_id="A", order_date=date(2024, 1, 10))
    for name, cents in items:
        order.add_item(AmazonItem(name=name, total_cents=cents))
    txn = TxnView(id=1, amount_cents=charge_cents, date=date(2024, 1, 11),
                  payee_name="Amazon", notes=notes, raw=raw)
    result = match_orders([order], [txn], tolerance_cents=2)
    assert result.matches, "fixture should match"
    return result.matches[0]


def test_balance_amounts_forces_exact_sum():
    assert balance_amounts([-1776, -2600], -4376) == [-1776, -2600]
    # residual goes to the largest-magnitude element
    assert balance_amounts([-1000, -2000], -3001) == [-1000, -2001]
    assert sum(balance_amounts([-1, -1, -1], -10)) == -10


def test_split_exact_two_items():
    m = _match(items=[("Trash Bags", 1776), ("Mouthwash", 2600)], charge_cents=-4376)
    plan = plan_split(m, MemoOptions())
    assert plan.action == "split"
    assert [c.amount_cents for c in plan.children] == [-1776, -2600]
    assert sum(c.amount_cents for c in plan.children) == -4376
    assert [c.notes for c in plan.children] == ["Trash Bags", "Mouthwash"]


def test_single_item_is_not_split():
    m = _match(items=[("Only Thing", 999)], charge_cents=-999)
    assert plan_split(m, MemoOptions()).action == "skip-single"


def test_not_exact_when_item_prices_missing():
    # Items have no price (extension-style order-total-only data) -> not-exact.
    order = AmazonOrder(order_id="B", order_date=date(2024, 1, 10))
    order.add_item(AmazonItem(name="A", total_cents=0))
    order.add_item(AmazonItem(name="B", total_cents=0))
    order.total_override_cents = 5000
    txn = TxnView(id=9, amount_cents=-5000, date=date(2024, 1, 11), payee_name="Amazon")
    m = match_orders([order], [txn]).matches[0]
    plan = plan_split(m, MemoOptions())
    assert plan.action == "not-exact"


def test_not_exact_when_items_dont_sum_to_charge():
    # Match cleanly at 2000, then perturb the charge so item totals no longer
    # reconcile; with zero tolerance the planner must refuse to split.
    order = AmazonOrder(order_id="C")
    order.add_item(AmazonItem(name="A", total_cents=1000))
    order.add_item(AmazonItem(name="B", total_cents=1000))
    txn = TxnView(id=3, amount_cents=-2000, date=date(2024, 1, 11), payee_name="Amazon")
    mm = match_orders([order], [txn]).matches[0]
    mm.txn.amount_cents = -2500  # now 2000 != 2500
    assert plan_split(mm, MemoOptions(), tolerance_cents=0).action == "not-exact"


def test_already_split_is_skipped():
    class FakeRaw:
        is_parent = 1
    m = _match(items=[("A", 1000), ("B", 1000)], charge_cents=-2000, raw=FakeRaw())
    assert plan_split(m, MemoOptions()).action == "skip-already"


def test_plan_splits_batch():
    m = _match(items=[("A", 1000), ("B", 1000)], charge_cents=-2000)
    plans = plan_splits([m], MemoOptions())
    assert len(plans) == 1 and plans[0].changes
