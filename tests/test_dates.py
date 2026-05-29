from datetime import date

from amazon_sync_for_actual.dates import days_between, parse_date


def test_iso_variants():
    assert parse_date("2024-01-10") == date(2024, 1, 10)
    assert parse_date("2024-01-10T08:00:00Z") == date(2024, 1, 10)
    assert parse_date("2024-01-10T08:00:00+00:00") == date(2024, 1, 10)


def test_us_and_textual():
    assert parse_date("01/10/2024") == date(2024, 1, 10)
    assert parse_date("1/5/24") == date(2024, 1, 5)
    assert parse_date("January 10, 2024") == date(2024, 1, 10)
    assert parse_date("Jan 10, 2024") == date(2024, 1, 10)


def test_passthrough_and_empty():
    assert parse_date(date(2024, 1, 1)) == date(2024, 1, 1)
    assert parse_date("") is None
    assert parse_date(None) is None
    assert parse_date("not a date") is None


def test_days_between():
    assert days_between(date(2024, 1, 1), date(2024, 1, 5)) == 4
    assert days_between(date(2024, 1, 5), date(2024, 1, 1)) == 4
    assert days_between(None, date(2024, 1, 1)) is None
