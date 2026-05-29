# Decisions & rationale

This document records what was changed and why, so it can be reviewed after the
fact. It was written during an autonomous session with the brief: *"examine this
repository, merge all branches, and take the idea as far as you can."*

## On "merge all branches"

There was nothing to merge. The only branches that exist are `master` and the
working branch for this session (`claude/compassionate-meitner-NQHxe`), and they
pointed at the **same commit** (verified with `git log master..HEAD` /
`HEAD..master`, both empty, and via the GitHub API which lists only `master`).
There are no open or closed pull requests. The historical `davidz627/*` branches
referenced in old merge commits were already merged into `master` long ago.

So "merge all branches" is a no-op, and the bulk of the work went into the second
half of the brief: making the idea actually work.

## Starting state: the fork was broken

The repo was a partially-completed fork of *Actual For YNAB*. The YNAB→Actual
migration was unfinished and the program could not run:

- `main.py` used `parser.*` and `matcher.*` **without importing** either module
  (immediate `NameError`), and read `secrets/credentials.ini` while the
  committed sample was misspelled `credientials.ini`.
- `actual_client.py` referenced `date`/`timedelta` it never imported, and talked
  to a **fictional** REST API (`https://api.actualbudget.com`, Bearer tokens,
  `/transactions/update`). Actual Budget has no such API — it is local-first and
  is driven through its sync server (Python: `actualpy`).
- `amazon_selenium_client.py` used the Selenium 3 API (`find_element_by_id`,
  the old `Chrome(executable, options=…)` constructor) that was **removed in
  Selenium 4**.
- `amazon_cookie_client.py` had a broken import; `amazon_firefox_client.py` was
  empty; `ynab_client.py` was dead code from the pre-fork tool.
- Tests depended on `test_data/` HTML fixtures that are `.gitignore`d and not in
  the repo, so they could not run. There was no CI.

## What was done

Rebuilt into a proper, installable, tested Python package
(`src/amazon_sync_for_actual/`) with a clean separation between pure logic and
external integrations.

### Architecture

| Module | Responsibility | Heavy deps? |
| --- | --- | --- |
| `money`, `dates`, `models` | Parsing & data model | none (stdlib) |
| `memo` | Build the note text from items | none |
| `matching` | Match orders/shipments ↔ transactions | none |
| `config` | Layered config (CLI > env > INI > default) | none |
| `sources/csv_source` | Parse Amazon CSV/dir/ZIP exports | none |
| `sources/invoice_html` | Parse invoice HTML | `bs4` (lazy) |
| `sources/selenium_source` | Experimental scraper | `selenium`, `pyotp` (lazy) |
| `actual_sync` | Plan + apply note updates | `actualpy` (lazy) |
| `cli` | Argument parsing & orchestration | none |

Optional dependencies are imported **lazily**, so the package imports and the
test suite run with none of them installed.

### Key design decisions

1. **CSV export is the primary data source, not scraping.** Amazon killed the
   one-click order report and actively blocks automation (CAPTCHAs, TOTP). The
   official "Request My Data → Your Orders" export
   (`Retail.OrderHistory.1.csv`) is deterministic, login-free and testable. The
   reader also accepts a directory or the raw ZIP and tolerates the legacy
   report's headers via an alias table. The Selenium path is kept but demoted to
   experimental.

2. **Match charges → order/shipment totals (not subset-sum).** The original tried
   to infer which items made up a charge — fundamentally ambiguous. With a real
   export we already know each order's and shipment's total, so we reverse it:
   for each Amazon transaction, find the order/shipment whose total equals the
   charge within a tolerance and whose date is within a window. Items are
   consumed once (no double-counting); matching one shipment leaves the order's
   other shipments available, so split charges work.

3. **Safe by default.** `--note-mode fill` only writes when a note is empty, so
   user-written notes are never destroyed. `append` and `overwrite` are opt-in.
   All modes are idempotent. `--dry-run` previews everything.

4. **`actualpy` for the Actual integration.** Verified against actualpy 0.22.2:
   connect with `Actual(base_url, password, file, encryption_password, cert)`,
   fetch via `get_transactions(session, start_date, end_date, …)`, amounts are
   integer cents (`get_amount()`/`set_amount()` use `Decimal`), dates via
   `get_date()`, persist with `commit()`. The sync layer's planning half is pure
   and unit-tested with fakes; only the thin connect/commit half needs the lib.

5. **Backwards compatibility.** The old flat `credentials.ini` `[DEFAULT]` keys
   (`actualBaseUrl`, `actualToken`, `userEmail`, `userPassword`, `otpSecret`)
   are still read and mapped onto the new config.

### Removed

- `src/ynab_client.py` — dead pre-fork code.
- `src/actual_client.py`, `src/main.py`, `src/parser.py`, `src/matcher.py`,
  `src/util.py`, `src/amazon_client/*` — replaced by the new package.
- `tests/context.py`, `tests/test_parser.py`, `tests/test_matcher.py` — replaced
  by a suite that runs without missing fixtures.
- `secrets/credientials.ini` — a committed sample with a typo'd name; replaced by
  root `config.example.ini` (and `secrets/` stays gitignored).
- `deploy.sh` — AWS Lambda packaging for the old tool that hardcoded a personal
  AWS account ARN and the old `amazonForYNAB` name; Selenium + actualpy on Lambda
  is impractical anyway.

### Added

- `pyproject.toml` (packaging, `amazon-sync-for-actual`/`asfa` entry points,
  extras: `selenium`, `dev`), updated `requirements.txt`, rewritten `Dockerfile`.
- 49 unit tests across parsing, dates, money, memo, matching, config, CSV import,
  invoice HTML, the planning layer and the CLI.
- GitHub Actions CI: test matrix on Python 3.9–3.12 plus a build job.
- Rewritten `README.md`, this `DECISIONS.md`, and `config.example.ini`.

## Browser extension (data gatherer)

Added a Manifest V3 browser extension under `extension/` to gather order data
from the user's already-authenticated Amazon session — avoiding stored
credentials, CAPTCHAs and the multi-day wait for the data export.

Decisions:

- **CSV is the contract.** The extension exports a CSV with the *exact* headers
  the Python importer reads (`Order ID, Order Date, …, Order Total, …, Currency`),
  so it's a drop-in for the data-export path. A committed end-to-end test
  (`tests/test_extension_csv.py`) parses an extension-shaped CSV and matches it,
  so the contract can't silently drift.
- **One extractor, all marketplaces.** Amazon's order pages share structure/CSS
  across regions, so a single `extractOrdersFromDocument` covers them. Currency is
  derived from the host (`currencyForHost`); labels are matched in English plus
  fr/de/es/it/pt. Order **totals** are read structurally, so even if a localized
  date label is missed the order is still captured and matched by amount.
- **Order-Total override in the importer.** Added `AmazonOrder.total_override_cents`
  and an `Order Total` column alias, because the order *list* page reliably shows
  the order total but not always per-item prices. Order-total wins over summed
  items when present.
- **No build step, no bundler.** `lib/parse.js` is a UMD-ish module usable by both
  the browser and `node --test`; logic that needs the DOM is isolated in
  `content.js` and tested with jsdom. Tests skip gracefully if jsdom is absent.
- **Privacy/permissions minimal.** `activeTab` + `storage` only; host matches are
  restricted to Amazon order pages; nothing leaves the browser.
- **MV3 + Chromium-first**, manifest kept simple enough to also load in Firefox.
  Icons are generated by `extension/icons/make_icons.py` (stdlib only).

## Local bridge: one-click extension → Actual

Added an optional local HTTP companion (`amazon-sync-for-actual --serve`,
`src/.../bridge.py`) so the extension can push orders straight into Actual
instead of only producing a file.

- **Why a bridge at all.** Actual has no simple "update transaction" REST
  endpoint; its sync server speaks a CRDT/binary protocol, and `actualpy` drives
  it by downloading the budget to local SQLite, mutating, and syncing back. That
  can't run in a browser content script, so the write must happen in a small
  local process. The bridge is the smallest thing that exposes the *existing*
  `ActualSyncer` (pull transactions → match → write notes) over HTTP.
- **It reuses, not duplicates, the write logic.** The handler calls the same
  `ActualSyncer.run` the CLI uses. `/preview` forces `dry_run=True`; `/sync`
  writes. This matches the user's own suggestion: find the matching transaction
  by pulling from Actual, then send a transaction-level note update down.
- **JSON ingestion.** Added `sources/json_source.py` (`orders_from_dicts`,
  `JsonSource`) so the extension's structured orders become `AmazonOrder`s; the
  CLI also accepts `--csv orders.json`. Accepts camelCase/snake_case and money as
  cents or strings.
- **Security.** Binds to **loopback only** (refuses non-127.0.0.1/localhost);
  optional shared token via `X-ASFA-Token`; `Origin` allow-list defaulting to
  browser-extension schemes; only a whitelist of request options
  (`note_mode`, `days`, `account`, …) can be overridden per call — the Actual
  connection details come from the server's launch config, so a web page can't
  redirect writes elsewhere.
- **Testable seam.** Socket-free core (`process_request`, `result_to_dict`,
  `apply_options`) plus an HTTP test that runs a real server on an ephemeral port
  with the actualpy-dependent step monkeypatched, so the whole thing is covered
  offline.
- **Extension UX.** A settings panel (bridge URL/token, note mode, account,
  look-back) and **Preview / Send to Actual** buttons; `host_permissions` for
  `127.0.0.1`/`localhost` added to the manifest so the popup can reach the bridge.

## Diagnostics / telemetry (local-first, redacted)

Added so extraction problems are *actionable* without violating the
"everything stays in the browser" model.

- **What it is.** As you browse order pages, the content script records a
  redacted per-page report (`extension/lib/diagnostics.js`): coverage counts
  (cards → id/date/total/items), which card selector matched, and for each failed
  field the value **shape** plus nearby CSS class names.
- **Privacy by construction.** No item names, order ids, addresses, names or real
  amounts are ever stored. Money/dates are reduced to shapes (`$#,###.##`,
  `## Xxxxxxxx ####`); free text is scrubbed of urls/order-ids/long digits; only
  class tokens (app chrome) and counts remain. A jsdom test asserts known values
  (`99.95`, product names, order ids) never appear in the serialized report.
- **Local-first, opt-out.** Reports go to a capped (300) ring buffer in
  `chrome.storage.local`; nothing is transmitted. The popup's **Diagnostics**
  panel previews/downloads/clears them and has an on/off toggle (`diagEnabled`).
- **Actionable on our side.** `--diag-report FILE` (`diagnostics.py`,
  `summarize_file`) renders a downloaded report into a per-marketplace coverage
  table and ranked failure patterns. Pure/stdlib, fully tested; it also recomputes
  a summary from raw reports if needed.
- **Why not auto-upload.** Telemetry that phones home would break the privacy
  promise and require a server. Download-and-share keeps the user in control and
  the architecture serverless; the bridge remains opt-in and unchanged.

## Cross-marketplace compatibility

Documented in `COMPATIBILITY.md`. Goal per request: every English-first
marketplace (US, CA, UK, AU/NZ, IN, SG, IE, AE, ZA) works via **both** the CSV
export and the extension.

- **CSV export is marketplace-proof**: Amazon generates it with English headers
  and ISO-8601 dates regardless of region, plus an explicit `Currency` column.
- **Locale money/dates**: the parsers handle `£/€/₹/A$/S$/R/AED`, comma-decimals
  (`19,99`), thin-space thousands (`1 234,56`), Indian lakh grouping, and several
  date spellings — covered by `tests/test_money.py` / `tests/test_dates.py` and
  the JS `parse.test.js`.
- **Known gap**: French/other month *names* in scraped/extension dates aren't
  normalized yet (e.g. amazon.ca French `10 janvier 2024`); the order is still
  captured and matched by amount (date is only a tie-breaker). Tracked as a small
  follow-up.
- **Known caveat**: matching keys on the integer amount, not the currency code,
  so a *multi-currency* budget could in principle swap two same-total orders in
  the same week. Mitigate with `--account`/`--date-window-days`; a same-currency
  guard is a candidate enhancement.

## Things a reviewer should weigh in on

- **Default `payee_regex`** includes Amazon-adjacent brands (Whole Foods, Prime
  Video, Kindle, Audible). Narrow it if that's too broad for your books.
- **Default note mode is `fill`** (never overwrite). If you'd rather always
  refresh notes, switch the default to `overwrite`.
- **Selenium backend**: it's updated for Selenium 4 but unverifiable here (no
  Amazon account/browser). It may need selector tweaks against the live site.
  Consider dropping it entirely in favor of CSV-only.
- **Could not run live integration** in this environment (no Actual server, no
  Amazon credentials, and `actualpy` can't install over Debian's system
  `cryptography` here — it installs cleanly in a fresh venv/CI). All offline
  unit tests pass; the live connect/commit path is covered by reading and mirrors
  actualpy's documented API.
