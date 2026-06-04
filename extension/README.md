# Amazon Sync for Actual — browser extension

A small Manifest V3 browser extension that gathers your Amazon order details
straight from your **already-logged-in** Amazon session and exports a CSV that
[Amazon Sync for Actual](../README.md) imports directly. No credentials are
stored, no scraping bots, no waiting days for the data export.

It works on **all English-first-language Amazon marketplaces** (and more) — see
[`../COMPATIBILITY.md`](../COMPATIBILITY.md).

## Why an extension?

The CSV "Request My Data" export is reliable but slow (Amazon emails it hours to
a day later). The extension reads the same order data live from the *Your Orders*
page you can already see, and writes a CSV with the **exact headers the importer
reads** — so it's a drop-in, faster alternative.

## Package it

Build an installable ZIP (stdlib only, no Node/bundler). It contains only the
runtime files — never tests, `node_modules`, or build scripts:

```bash
cd extension
python3 build.py            # -> extension/dist/amazon-sync-for-actual-extension-<version>.zip
```

The script validates the manifest, prints the file list, size and a SHA-256, and
fails if any referenced script is missing from its whitelist. The same build runs
in CI and uploads the zip as an artifact.

## Install

You can install either the **packaged ZIP** or the **unpacked folder** — both
contain the same files.

**Chrome / Edge / Brave (Chromium):**
1. Go to `chrome://extensions` and enable **Developer mode**.
2. Either **Load unpacked** → select this `extension/` folder, *or* unzip the
   built package and **Load unpacked** → select the unzipped folder.
   *(Chromium only installs a raw `.zip` directly when it is signed/from the Web
   Store, so for local installs you load the folder — drag-and-drop of an
   unpacked dir also works.)*

**Firefox:**
1. Go to `about:debugging#/runtime/this-firefox`.
2. **Load Temporary Add-on…** → select `extension/manifest.json` (or the
   `manifest.json` inside the unzipped package).

(Chromium MV3 is the primary target; the manifest is kept simple so it also
loads in current Firefox. Publishing to the Chrome Web Store / AMO uses the same
ZIP — that's a separate listing step.)

## Use

1. Open Amazon and go to **Returns & Orders** (your order history).
2. Click the extension icon, then choose how much to collect:
   - **Scan this page** — just the orders currently shown.
   - **Scan all pages** — auto-walks every page of the current view by following
     the real *Next* link (no manual clicking). Live progress shows in the popup.
   - **Scan entire history (all years)** — walks every time filter (each year and
     the rolling windows) and every page within, collecting the whole account in
     one go.
   Scans accumulate and de-duplicate, so you can combine them safely. The
   **Per-year summary** in the popup updates live (orders / items / total per
   calendar year) so you can confirm coverage — e.g. spot a year that didn't get
   scanned.
3. Click **Download CSV**.
4. Feed it to the tool (preview first):

   ```bash
   amazon-sync-for-actual --csv amazon-orders-YYYY-MM-DD.csv \
     --actual-url http://localhost:5006 --actual-password "$PW" \
     --actual-file "My Budget" --dry-run
   ```

**Download JSON** is also available if you want the raw structured data.

### One-click: Send to Actual (via the local bridge)

Instead of downloading a file, you can push orders straight into Actual:

1. Start the bridge on your machine:

   ```bash
   amazon-sync-for-actual -c config.ini --serve      # http://127.0.0.1:5007
   ```

2. In the extension, open **Settings ⚙** and set the **Bridge URL** (default
   `http://127.0.0.1:5007`), an optional **token** (matching `--bridge-token`),
   the **note mode** (fill / prepend / append / overwrite), and optionally an
   account / look-back days. Click **Save settings**.
3. Scan your orders, then click **Preview in Actual** (dry-run, shows what would
   change) or **Send to Actual** (writes the notes).

The bridge runs locally, binds to loopback only, and reuses the CLI's matching
logic. The extension needs host permission for `127.0.0.1`/`localhost` (declared
in the manifest) to reach it.

## Diagnostics (help improve extraction)

Amazon changes its markup often and differs subtly between marketplaces, so the
extension can record **how well extraction is working** as you browse — and it
does so **without capturing any personal data**.

Open **Diagnostics 🧪** in the popup. With it enabled (default), each order page
you visit appends a *redacted* record to local storage:

- coverage counts (how many order cards yielded an id / date / total / items),
- which CSS card selector matched,
- for any field that failed, the **shape** of the value (e.g. a price becomes
  `$#,###.##`, a date becomes `## Xxxxxxxx ####`) and the nearby CSS class names.

Crucially, it never stores item names, order ids, addresses, names, or actual
amounts — only formats, counts and class names. Click **Preview report** to see
the summary, or **Download report** to save `asfa-diagnostics-YYYY-MM-DD.json`
and share it. You (or a maintainer) can turn it into a readable verdict with:

```bash
amazon-sync-for-actual --diag-report asfa-diagnostics-YYYY-MM-DD.json
```

That prints per-marketplace coverage and the top failure patterns — exactly what
is needed to fix a selector. Untick the checkbox to stop recording, or
**Clear diagnostics** to wipe what's stored. Everything stays in your browser.

## What it extracts

Per order: order id, order date, order **total**, currency (from the
marketplace), and each item's name + ASIN + quantity (and unit price when shown).
The CSV uses the importer's `Order Total` column, so orders match even when Amazon
doesn't show reliable per-item prices on the list page.

CSV columns: `Order ID, Order Date, Ship Date, Product Name, Quantity, Unit
Price, Total Owed, Order Total, ASIN, Currency`.

## Privacy

- Runs only on Amazon order pages (`content_scripts.matches` in the manifest).
- Reads only what you can already see while logged in. Nothing is sent anywhere —
  collected data lives in the extension's local storage until you download or
  **Clear** it. No analytics, no servers, no credentials.

## Permissions

- `activeTab` / host match on Amazon order pages — to read the current orders page.
- `storage` — to accumulate orders across scans until you export.

## Files

| File | Purpose |
|---|---|
| `manifest.json` | MV3 manifest; marketplace host match patterns |
| `lib/parse.js` | Pure helpers (money/date/CSV/merge) — shared with tests |
| `content.js` | DOM extraction from order pages (`extractOrdersFromDocument`) |
| `popup.html/.css/.js` | UI: scan, count, export CSV/JSON, clear |
| `icons/` | Generated PNGs (`make_icons.py` regenerates them) |
| `test/` | `node --test` unit + jsdom extraction tests |

## Develop & test

```bash
cd extension
npm install        # installs jsdom (dev only)
npm test           # node --test
```

DOM-extraction tests are skipped automatically if `jsdom` isn't installed; the
pure-helper tests always run. Selectors are best-effort — if Amazon changes its
markup, update `content.js` and add a fixture under `test/fixtures/`.
