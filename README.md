# Amazon Sync for Actual

Amazon charges show up in [Actual Budget](https://actualbudget.org) as a bare
`Amazon.com` with no hint of *what* you bought, which makes categorizing and
reviewing them painful. **Amazon Sync for Actual** reads your Amazon order
history, matches each order (or shipment) to the corresponding transaction in
Actual, and writes the item names into the transaction's note.

```
Before:  2024-01-11   -$43.76   Amazon.com
After:   2024-01-11   -$43.76   Amazon.com   "Glad Tall Kitchen Trash Bags | Crest ProHealth Mouthwash"
```

> **Project status.** This repository began as a fork of *Actual For YNAB* and
> the YNAB→Actual migration was left half-finished and non-functional (missing
> imports, a fictional Actual REST API, Selenium 3 calls removed in Selenium 4,
> tests that depended on files excluded from git). It has been rebuilt into a
> working, tested, installable tool. See [`DECISIONS.md`](DECISIONS.md) for the
> full rationale and the list of what changed.

## How it works

1. **Read** your Amazon orders — from a CSV export, the browser extension
   (CSV/JSON, or a direct push via the local bridge), or scraping (experimental).
   Each order becomes a list of items with an all-in total.
2. **Match** each Amazon transaction in Actual to the order or shipment whose
   total equals the charge and whose date is within a configurable window. Items
   are consumed once, so a single purchase is never attributed to two charges,
   and split shipments charged separately are matched individually.
3. **Write** the item names into the transaction note. By default this only
   fills *empty* notes (it never clobbers notes you wrote yourself); with
   `--note-mode` you can instead `prepend`, `append`, or `overwrite`. Every mode
   is idempotent — re-running makes no duplicate changes.

   Alternatively, `--split-mode items` turns a matched transaction into a
   **split** — one child subtransaction per item, each carrying that item's name
   (and ready for its own category). To keep your books balanced this only
   happens when the item amounts reconcile to the charge **exactly** (i.e. the
   data has real per-item prices, as in the "Request My Data" export); otherwise
   it falls back to a single note. Already-split transactions are left untouched.

The data-wrangling core (parsing, matching, memo building) has no heavy
dependencies and is fully unit-tested. `actualpy` and `selenium` are imported
lazily, so importing the package never requires them.

## Install

```bash
pip install .            # from a checkout
# or, once published:
# pip install amazon-sync-for-actual
```

This installs the `amazon-sync-for-actual` (and short alias `asfa`) command.
Talking to Actual uses [`actualpy`](https://github.com/bvanelli/actualpy), which
is pulled in automatically.

## Step 1 — get your Amazon order data

You have two ways to produce the order CSV. Both work on **all English Amazon
marketplaces** (amazon.com, .ca, .co.uk, .com.au, .in, .sg, .ie, .ae, .co.za)
and more — see [`COMPATIBILITY.md`](COMPATIBILITY.md).

**Option A — Browser extension (fastest).** The bundled [`extension/`](extension/)
reads orders straight from your logged-in *Your Orders* page and downloads a
ready-to-import CSV. No credentials stored, no waiting. See
[`extension/README.md`](extension/README.md) to load it.

**Option B — Official data export (no install).** Amazon's standardized export:

1. Go to **Account → Privacy Central → [Request My Data](https://www.amazon.com/gp/privacycentral/dsar/preview.html)**.
2. Choose **"Your Orders"** and submit. Amazon emails you a ZIP (hours to a day).
3. The useful file inside is `Retail.OrderHistory.1/Retail.OrderHistory.1.csv`.

You can point the tool at an unzipped CSV, a directory, or the raw ZIP — it finds
the order file either way. The older "Order history report" CSV and the
extension's CSV are all understood via header aliases.

## Step 2 — point it at Actual

You connect to your Actual **sync server** (the same server the Actual app syncs
to), not a hosted API. You need its URL, the server password, and your budget's
name.

## Step 3 — run it (dry-run first!)

Always preview first; nothing is written to Actual on a dry run:

```bash
amazon-sync-for-actual \
  --csv Retail.OrderHistory.1.csv \
  --actual-url http://localhost:5006 \
  --actual-password "$ACTUAL_PASSWORD" \
  --actual-file "My Budget" \
  --dry-run
```

When the plan looks right, drop `--dry-run` to apply it.

To just inspect what the parser sees, without touching Actual at all:

```bash
amazon-sync-for-actual --csv ./amazon-data.zip --list-orders
```

### One-click sync from the extension (the bridge)

Instead of downloading a CSV, you can let the browser extension push orders
straight into Actual. Because Actual has no plain REST API (it uses a CRDT sync
protocol), a tiny **local** companion does the write using the same matching
logic as the CLI:

```bash
amazon-sync-for-actual -c config.ini --serve      # runs on http://127.0.0.1:5007
```

Then in the extension's **Settings**, set the bridge URL (and token, if you used
`--bridge-token`), pick a note mode, and click **Preview in Actual** or **Send to
Actual**. The bridge:

- pulls your transactions from Actual, matches them to the posted orders, and
  writes per-transaction notes back down (honoring `note_mode`);
- binds to **loopback only** and can require a shared token (`--bridge-token` /
  `ASFA_BRIDGE_TOKEN`) sent as the `X-ASFA-Token` header;
- exposes `GET /health`, `POST /preview` (always dry-run) and `POST /sync`.

### Diagnostics

The extension can record **redacted** extraction health as you browse (no item
names, order ids, or amounts — only coverage counts, CSS class hints and value
*shapes*). Download the report from its **Diagnostics** panel and turn it into a
readable per-marketplace verdict with:

```bash
amazon-sync-for-actual --diag-report asfa-diagnostics-YYYY-MM-DD.json
```

See [`extension/README.md`](extension/README.md#diagnostics-help-improve-extraction)
for what is and isn't captured.

### Configuration file

Copy [`config.example.ini`](config.example.ini) to `config.ini` (gitignored)
and run `amazon-sync-for-actual -c config.ini`. Precedence is
**CLI flag > `ASFA_*` environment variable > config file > default**. The
original `credentials.ini` `[DEFAULT]` keys (`actualBaseUrl`, `otpSecret`, …)
are still recognized for backwards compatibility.

### Useful options

| Option | Meaning | Default |
| --- | --- | --- |
| `--days N` / `--start` / `--end` | Transaction window to consider | last 90 days |
| `--date-window-days N` | Max gap between a charge and an order date | 5 |
| `--tolerance-cents N` | Allowed rounding difference when matching totals | 0 |
| `--payee-regex RE` | Which payees count as Amazon | `amazon\|amzn\|…` |
| `--note-mode` | `fill` (only if empty), `prepend`, `append`, or `overwrite` | `fill` |
| `--split-mode` | `off`, or `items` to split a matched transaction into one child per item (only when item amounts reconcile exactly; otherwise falls back to a note) | `off` |
| `--no-shipments` | Match whole-order totals only | shipments on |
| `--include-positive` | Also annotate refunds | off |
| `--max-words-per-item`, `--max-items`, `--separator`, `--note-prefix`, `--max-length` | Note formatting | — |
| `--account NAME` | Limit to one Actual account | all |

Run `amazon-sync-for-actual --help` for the complete list.

## Experimental: scraping with Selenium

A best-effort Selenium backend is kept for backwards compatibility. It is
fragile (Amazon changes its markup and may show CAPTCHAs) — prefer the CSV path.

```bash
pip install ".[selenium]"
amazon-sync-for-actual --source selenium \
  --amazon-email you@example.com --amazon-password "$AMZ_PW" \
  --amazon-otp-secret "$TOTP_SECRET" \
  --actual-url http://localhost:5006 --actual-password "$ACTUAL_PASSWORD" \
  --actual-file "My Budget" --dry-run
```

`otp_secret` is only needed if your account uses TOTP 2FA: set up an
authenticator, and the QR code's `secret=` parameter is the value to use.

## Docker

```bash
docker build -t amazon-sync-for-actual .
docker run --rm \
  -v "$PWD/config.ini:/config/config.ini:ro" \
  -v "$PWD/Retail.OrderHistory.1.csv:/data/orders.csv:ro" \
  amazon-sync-for-actual -c /config/config.ini --csv /data/orders.csv --dry-run
```

Secrets and order data are mounted at runtime; nothing sensitive is baked into
the image.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The suite runs entirely offline — no Actual server, Amazon account, or optional
dependency required.

## Marketplace compatibility

Both the CSV export and the browser extension target **every English-first
marketplace** (US, CA, UK, AU/NZ, IN, SG, IE, AE, ZA), with money/date/currency
handling verified by tests; many non-English marketplaces work too. The CSV
export is marketplace-proof (English headers, ISO dates) and the extension uses a
single extractor across regions. Full matrix and caveats:
[`COMPATIBILITY.md`](COMPATIBILITY.md).

## Limitations

- Matching is by amount + date proximity; genuinely ambiguous cases (two
  different orders, same total, same week) may match the wrong one. Use
  `--tolerance-cents`/`--date-window-days` to tune, and `--dry-run` to review.
- Gift-card splits, points/coupons and currency conversions can make a charge
  not equal any order total; those simply go unmatched (and are reported).
- The Selenium backend is best-effort and unsupported.

See [`DECISIONS.md`](DECISIONS.md) for design rationale and trade-offs.

## License

MIT — see [`COPYING`](COPYING). Originally based on *Actual For YNAB* by David
Zhu.
