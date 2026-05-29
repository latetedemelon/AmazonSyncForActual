from amazon_sync_for_actual.memo import MemoOptions, build_memo
from amazon_sync_for_actual.models import AmazonItem


def test_basic_join_and_quantity():
    items = [
        AmazonItem(name="Trash Bags Tall Kitchen", quantity=1),
        AmazonItem(name="AAA Batteries 24 Pack", quantity=2),
    ]
    memo = build_memo(items)
    assert memo == "Trash Bags Tall Kitchen | 2x AAA Batteries 24 Pack"


def test_word_truncation():
    items = [AmazonItem(name="one two three four five six seven eight nine")]
    memo = build_memo(items, MemoOptions(max_words_per_item=3))
    assert memo == "one two three"


def test_max_items_summary():
    items = [AmazonItem(name=f"Item{i}") for i in range(5)]
    memo = build_memo(items, MemoOptions(max_items=2, include_quantity=False))
    assert memo == "Item0 | Item1 | +3 more"


def test_prefix_and_max_length():
    items = [AmazonItem(name="A very long product name indeed")]
    memo = build_memo(items, MemoOptions(prefix="Amazon: ", max_length=15))
    assert memo.endswith("…")
    assert len(memo) == 15


def test_empty():
    assert build_memo([]) == ""
    assert build_memo([AmazonItem(name="   ")]) == ""
