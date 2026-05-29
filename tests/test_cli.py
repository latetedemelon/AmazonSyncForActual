import os

import pytest

from conftest import DATA

from amazon_sync_for_actual.cli import main

RETAIL = os.path.join(DATA, "retail_order_history_sample.csv")


def test_list_orders(capsys):
    rc = main(["--csv", RETAIL, "--list-orders"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "112-1111111-1111111" in out
    assert "order(s)" in out


def test_sync_requires_csv_path(capsys):
    rc = main(["--source", "csv", "--dry-run"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "csv" in err.lower()


def test_version():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
