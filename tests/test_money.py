from decimal import Decimal

from amazon_sync_for_actual.money import cents_to_str, parse_decimal, to_cents


def test_parse_plain_and_symbols():
    assert parse_decimal("12.34") == Decimal("12.34")
    assert parse_decimal("$12.34") == Decimal("12.34")
    assert parse_decimal("USD 12.34") == Decimal("12.34")
    assert parse_decimal("  $1,234.56 ") == Decimal("1234.56")


def test_parse_negatives_and_parens():
    assert parse_decimal("-5.00") == Decimal("-5.00")
    assert parse_decimal("($5.00)") == Decimal("-5.00")


def test_parse_european_and_comma_decimal():
    assert parse_decimal("1.234,56") == Decimal("1234.56")
    assert parse_decimal("12,34") == Decimal("12.34")


def test_parse_empty_and_garbage():
    assert parse_decimal("") is None
    assert parse_decimal(None) is None
    assert parse_decimal("n/a") is None
    assert parse_decimal(True) is None


def test_to_cents_rounding():
    assert to_cents("17.76") == 1776
    assert to_cents("0") == 0
    assert to_cents("12.345") == 1235  # round half up
    assert to_cents("") is None


def test_cents_to_str():
    assert cents_to_str(1776) == "17.76"
    assert cents_to_str(-500, "$") == "$-5.00"
    assert cents_to_str(5) == "0.05"
