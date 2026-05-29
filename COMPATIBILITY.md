# Marketplace compatibility

This documents how well Amazon Sync for Actual works across Amazon's regional
marketplaces, by data source. The explicit goal is **every English-first-language
marketplace working via both the CSV export and the browser extension**; other
marketplaces are supported on a best-effort basis and largely work for free.

## TL;DR

- **CSV export** (`Request My Data` → *Your Orders*) is **standardized**:
  English column headers and ISO‑8601 dates **regardless of marketplace**. It is
  the most reliable path and works everywhere.
- The **browser extension** uses one extractor for all marketplaces (Amazon's
  order pages share the same structure/CSS), with English + multilingual label
  matching and per‑marketplace currency tagging.
- Matching compares amounts **in your budget's own currency** (no FX), so a CAD
  budget + CAD orders, a GBP budget + GBP orders, etc. all reconcile correctly.

## Status by marketplace

Legend: ✅ supported & tested · ☑️ supported (same code path, not separately
fixtured) · ⚠️ best‑effort · ❌ not supported.

### English first-language marketplaces (target)

| Marketplace | Domain | Currency | CSV export | Extension | Notes |
|---|---|---|---|---|---|
| United States | amazon.com | USD | ✅ | ✅ tested | Reference marketplace |
| Canada | amazon.ca | CAD | ✅ | ☑️ | English + French; see note below |
| United Kingdom | amazon.co.uk | GBP | ✅ | ✅ tested | `£`, `DD Month YYYY` dates |
| Australia | amazon.com.au | AUD | ✅ | ☑️ | `A$`; also serves New Zealand |
| New Zealand | (uses .com.au / .com) | NZD/AUD/USD | ✅ | ☑️ | No standalone NZ store; shop on AU/US |
| India | amazon.in | INR | ✅ | ☑️ | `₹`, lakh grouping (`1,23,456.78`) |
| Singapore | amazon.sg | SGD | ✅ | ☑️ | `S$` |
| Ireland | amazon.ie | EUR | ✅ | ☑️ | `€` |
| UAE | amazon.ae | AED | ✅ | ☑️ | English/Arabic |
| South Africa | amazon.co.za | ZAR | ✅ | ☑️ | `R` |

### Other marketplaces (handled, best-effort)

| Marketplace | Domain | Currency | CSV export | Extension |
|---|---|---|---|---|
| Mexico | amazon.com.mx | MXN | ✅ | ⚠️ Spanish labels |
| Brazil | amazon.com.br | BRL | ✅ | ⚠️ Portuguese labels |
| Germany | amazon.de | EUR | ✅ | ⚠️ German labels |
| France | amazon.fr | EUR | ✅ | ⚠️ French labels |
| Spain / Italy / NL / BE | amazon.es/.it/.nl/.com.be | EUR | ✅ | ⚠️ |
| Sweden / Poland / Turkey | amazon.se/.pl/.com.tr | SEK/PLN/TRY | ✅ | ⚠️ |
| Japan | amazon.co.jp | JPY | ✅ | ⚠️ Zero‑decimal currency |
| Saudi Arabia / Egypt | amazon.sa/.eg | SAR/EGP | ✅ | ⚠️ |

> The extension's label matcher includes English plus French/German/Spanish/
> Italian/Portuguese terms, so several non‑English stores work today; others
> still capture the **order id, total and item names** (the essentials) even if a
> localized date label is missed, because order totals are read structurally.

## Why the CSV path is marketplace-proof

Amazon's GDPR/CCPA data export (`Retail.OrderHistory.1.csv`) is generated
server‑side in a fixed schema:

- **Headers are English** on every marketplace: `Order ID`, `Order Date`,
  `Total Owed`, `Product Name`, `Quantity`, `Currency`, …
- **Dates are ISO‑8601** (`2024-01-10T08:00:00Z`).
- A **`Currency`** column states the order currency explicitly.

The importer additionally tolerates locale‑formatted money (`19,99 €`,
`1 234,56 $`, `₹1,23,456.78`, parenthesised credits) and several date spellings,
so even hand‑made or legacy CSVs parse. Verified by unit tests in
`tests/test_money.py`, `tests/test_dates.py`, and `tests/test_csv_source.py`.

## Currency handling & one caveat

- Money is parsed to **integer minor units** and matched within a single
  currency; there is **no FX conversion**. Keep one marketplace's orders aligned
  with the account/budget that was charged in that currency.
- **Caveat (multi‑currency budgets):** the matcher currently keys on the cent
  amount, not the currency code, so in a budget mixing currencies two orders with
  an identical integer total in the same date window could in principle be
  swapped. This is rare; mitigate with `--account` (scope to the card used) or a
  tighter `--date-window-days`. A same‑currency match guard is a candidate
  enhancement (see `DECISIONS.md`).
- **Zero‑decimal currencies (e.g. JPY):** amounts have no minor unit. The
  importer/exporter treat values as ×100 cents consistently, so JPY orders match
  JPY transactions as long as both come through the same pipeline; mixing a
  ×100‑scaled CSV with a non‑scaled one would be wrong. The CSV export path is
  internally consistent here.

## A note on amazon.ca French

For the **CSV** path, French has no impact — the export is English/ISO. For the
**extension** and the legacy invoice scraper, French *month names*
(`10 janvier 2024`) are not yet parsed into a normalized date; the order is still
captured (id, total, items) and matched by amount, with the date used only as a
tie‑breaker. Adding French/locale month parsing is a tracked enhancement.

## How this is tested

- **Python:** `tests/test_money.py`, `tests/test_dates.py`,
  `tests/test_csv_source.py` (incl. an extension‑style Order‑Total CSV) and
  `tests/test_extension_csv.py` (full parse of a committed multi‑marketplace CSV).
- **Extension:** `extension/test/parse.test.js` (currency map + money/date for
  US/UK/AU/SG/IN/ZA/AE/EUR) and `extension/test/extract.test.js` (jsdom
  extraction of amazon.com and amazon.co.uk order pages).
