"""Command-line interface.

Examples::

    # See what would change without touching Actual (recommended first run):
    amazon-sync-for-actual --csv Retail.OrderHistory.1.csv \
        --actual-url http://localhost:5006 --actual-password secret \
        --actual-file "My Budget" --dry-run

    # Just parse a CSV export and print the orders (no Actual needed):
    amazon-sync-for-actual --csv ./amazon-data.zip --list-orders
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional, Sequence

from . import __version__
from .config import Config, load_config
from .money import cents_to_str

log = logging.getLogger("amazon_sync_for_actual")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="amazon-sync-for-actual",
        description="Enrich Amazon transactions in Actual Budget with order item details.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-c", "--config", dest="config_path", help="Path to an INI config file.")

    # Actions
    p.add_argument(
        "--list-orders",
        action="store_true",
        help="Only parse the Amazon source and print the orders; never touch Actual.",
    )
    p.add_argument(
        "--serve",
        action="store_true",
        help="Run the local HTTP bridge so the browser extension can push orders to Actual.",
    )
    p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=None,
        help="Plan changes against Actual but do not write/commit them.",
    )
    p.add_argument(
        "-v", "--verbose", dest="verbose", action="store_true", default=None,
        help="Verbose logging.",
    )

    # Bridge
    g = p.add_argument_group("Bridge (with --serve)")
    g.add_argument("--host", dest="bridge_host", help="Bridge bind host (loopback only).")
    g.add_argument("--port", dest="bridge_port", type=int, help="Bridge port (default 5007).")
    g.add_argument("--bridge-token", dest="bridge_token",
                   help="Require this token (X-ASFA-Token header) on bridge writes.")

    # Actual connection
    g = p.add_argument_group("Actual connection")
    g.add_argument("--actual-url", dest="actual_url")
    g.add_argument("--actual-password", dest="actual_password")
    g.add_argument("--actual-token", dest="actual_token")
    g.add_argument("--actual-file", dest="actual_file", help="Budget name or sync id.")
    g.add_argument("--actual-encryption-password", dest="actual_encryption_password")
    g.add_argument("--actual-cert", dest="actual_cert", help="true/false or path to CA bundle.")
    g.add_argument("--account", dest="account", help="Limit to one account name.")

    # Source
    g = p.add_argument_group("Amazon source")
    g.add_argument("--source", choices=["csv", "selenium"], dest="source")
    g.add_argument("--csv", dest="csv_path", help="CSV file, directory, or export ZIP.")
    g.add_argument("--amazon-email", dest="amazon_email")
    g.add_argument("--amazon-password", dest="amazon_password")
    g.add_argument("--amazon-otp-secret", dest="amazon_otp_secret")
    g.add_argument("--pages", dest="selenium_pages", type=int, help="Order-history pages to scrape.")

    # Matching
    g = p.add_argument_group("Matching")
    g.add_argument("--days", dest="days", type=int, help="Look back this many days (default 90).")
    g.add_argument("--start", dest="start_date", help="Start date (YYYY-MM-DD).")
    g.add_argument("--end", dest="end_date", help="End date (YYYY-MM-DD).")
    g.add_argument("--date-window-days", dest="date_window_days", type=int)
    g.add_argument("--tolerance-cents", dest="tolerance_cents", type=int)
    g.add_argument("--payee-regex", dest="payee_regex")
    g.add_argument(
        "--no-shipments", dest="match_shipments", action="store_false", default=None,
        help="Match whole-order totals only (don't consider per-shipment subtotals).",
    )
    g.add_argument(
        "--include-positive", dest="include_positive", action="store_true", default=None,
        help="Also match positive amounts (refunds).",
    )

    # Memo
    g = p.add_argument_group("Memo / notes")
    g.add_argument(
        "--note-mode",
        choices=["fill", "prepend", "append", "overwrite"],
        dest="note_mode",
        help="How to write notes: fill (only if empty), prepend, append, or overwrite.",
    )
    g.add_argument("--max-words-per-item", dest="max_words_per_item", type=int)
    g.add_argument("--max-items", dest="max_items", type=int)
    g.add_argument("--separator", dest="separator")
    g.add_argument(
        "--no-quantity", dest="include_quantity", action="store_false", default=None,
        help="Do not prefix items with their quantity.",
    )
    g.add_argument("--note-prefix", dest="note_prefix")
    g.add_argument("--max-length", dest="max_length", type=int)
    return p


def _overrides_from_args(args: argparse.Namespace) -> dict:
    """Collect every Config-bound arg (None values are ignored by load_config)."""
    keys = [
        "actual_url", "actual_password", "actual_token", "actual_file",
        "actual_encryption_password", "actual_cert", "account",
        "source", "csv_path", "amazon_email", "amazon_password",
        "amazon_otp_secret", "selenium_pages",
        "days", "start_date", "end_date", "date_window_days", "tolerance_cents",
        "payee_regex", "match_shipments", "include_positive",
        "note_mode", "max_words_per_item", "max_items", "separator",
        "include_quantity", "note_prefix", "max_length",
        "bridge_host", "bridge_port", "bridge_token",
        "dry_run", "verbose",
    ]
    return {k: getattr(args, k) for k in keys if getattr(args, k, None) is not None}


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _print_orders(orders) -> None:
    total = 0
    for order in orders:
        total += order.total_cents
        date = order.order_date.isoformat() if order.order_date else "????-??-??"
        print(f"\nOrder {order.order_id}  {date}  {cents_to_str(order.total_cents, '$')}")
        for item in order.items:
            qty = f"{item.quantity}x " if item.quantity > 1 else ""
            print(f"    {cents_to_str(item.total_cents, '$'):>10}  {qty}{item.name}")
    print(f"\n{len(orders)} order(s), total {cents_to_str(total, '$')}")


def _print_plan(result) -> None:
    for update in result.updates:
        t = update.txn
        date = t.date.isoformat() if t.date else "????-??-??"
        marker = {
            "write": "WRITE ", "append": "APPEND", "prepend": "PREPND",
            "skip-existing": "KEEP  ", "skip-idempotent": "SAME  ",
            "empty-memo": "EMPTY ",
        }.get(update.action, update.action)
        print(f"[{marker}] {date}  {cents_to_str(t.amount_cents, '$'):>10}  {t.payee_name}")
        if update.changes:
            print(f"           -> {update.new_notes}")
    if result.unmatched_txns:
        print(f"\n{len(result.unmatched_txns)} Amazon transaction(s) had no matching order.")
    print("\nSummary:", result.summary())


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config_path, _overrides_from_args(args))
    except (ValueError, OSError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    _setup_logging(config.verbose)

    # ---- list-orders: source only, no Actual ----
    if args.list_orders:
        try:
            from .sources import build_source

            orders = build_source(config).fetch_orders()
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"Error reading Amazon source: {exc}", file=sys.stderr)
            return 2
        _print_orders(orders)
        return 0

    # ---- serve: run the local bridge for the browser extension ----
    if args.serve:
        try:
            from .bridge import run_server

            run_server(
                config,
                host=config.bridge_host,
                port=config.bridge_port,
                token=config.bridge_token,
            )
        except (ValueError, OSError) as exc:
            print(f"Bridge error: {exc}", file=sys.stderr)
            return 2
        return 0

    # ---- full sync (or dry-run) ----
    problems = config.validate()
    if problems:
        for problem in problems:
            print(f"Configuration error: {problem}", file=sys.stderr)
        return 2

    try:
        from .sources import build_source
        from .actual_sync import ActualSyncer

        orders = build_source(config).fetch_orders()
        if not orders:
            print("No Amazon orders found in the source; nothing to do.")
            return 0
        result = ActualSyncer(config).run(orders)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    _print_plan(result)
    if config.dry_run:
        print("\nDry-run: no changes were written to Actual.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
