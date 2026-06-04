/* Popup logic: talk to the content script, accumulate orders, export CSV/JSON. */
"use strict";

var orders = [];

function $(id) { return document.getElementById(id); }

function setStatus(msg, kind) {
  var el = $("status");
  el.textContent = msg || "";
  el.className = "status" + (kind ? " " + kind : "");
}

var DEFAULT_SETTINGS = {
  bridgeUrl: "http://127.0.0.1:5007",
  token: "",
  noteMode: "fill",
  account: "",
  days: ""
};
var settings = Object.assign({}, DEFAULT_SETTINGS);

function money(cents) {
  if (!cents) return "$0.00";
  return "$" + (Math.abs(cents) / 100).toFixed(2);
}

function renderByYear() {
  var body = $("byyear-body");
  if (!body) return;
  body.innerHTML = "";
  if (!orders.length) {
    body.innerHTML = '<tr class="empty"><td colspan="4">No orders collected yet.</td></tr>';
    return;
  }
  var summary = ASFA.summarizeOrdersByYear(orders);
  summary.rows.forEach(function (r) {
    var tr = document.createElement("tr");
    var label = r.year === "unknown" ? "(no date)" : r.year;
    tr.innerHTML = "<td>" + label + "</td><td>" + r.orders + "</td><td>" +
      r.items + "</td><td>" + money(r.totalCents) + "</td>";
    body.appendChild(tr);
  });
  var t = summary.totals;
  var totals = document.createElement("tr");
  totals.className = "totals";
  totals.innerHTML = "<td>All</td><td>" + t.orders + "</td><td>" + t.items +
    "</td><td>" + money(t.totalCents) + "</td>";
  body.appendChild(totals);
}

function render() {
  $("count").textContent = orders.length;
  $("items").textContent = orders.reduce(function (n, o) {
    return n + (o.items ? o.items.length : 0);
  }, 0);
  renderByYear();
}

async function load() {
  var data = await chrome.storage.local.get(["orders", "settings"]);
  orders = data.orders || [];
  settings = Object.assign({}, DEFAULT_SETTINGS, data.settings || {});
  applySettingsToForm();
  render();
}

async function save() {
  await chrome.storage.local.set({ orders: orders });
}

function applySettingsToForm() {
  $("s-bridge").value = settings.bridgeUrl;
  $("s-token").value = settings.token;
  $("s-notemode").value = settings.noteMode;
  $("s-account").value = settings.account;
  $("s-days").value = settings.days;
}

function readSettingsFromForm() {
  settings = {
    bridgeUrl: $("s-bridge").value.trim() || DEFAULT_SETTINGS.bridgeUrl,
    token: $("s-token").value,
    noteMode: $("s-notemode").value,
    account: $("s-account").value.trim(),
    days: $("s-days").value.trim()
  };
  return settings;
}

function buildOptions() {
  return ASFA.buildBridgeOptions(settings);
}

// POST the collected orders to the local bridge (/preview or /sync).
async function sendToBridge(path) {
  if (!orders.length) { setStatus("Nothing collected yet.", "error"); return; }
  var url = settings.bridgeUrl.replace(/\/+$/, "") + path;
  setStatus((path === "/sync" ? "Syncing" : "Previewing") + " via bridge…");
  try {
    var headers = { "Content-Type": "application/json" };
    if (settings.token) headers["X-ASFA-Token"] = settings.token;
    var resp = await fetch(url, {
      method: "POST",
      headers: headers,
      body: JSON.stringify({ orders: orders, options: buildOptions() })
    });
    var body = await resp.json().catch(function () { return {}; });
    if (!resp.ok || body.ok === false) {
      setStatus("Bridge error: " + (body.error || resp.status), "error");
      return;
    }
    var c = body.counts || {};
    var verb = body.wrote ? "Wrote" : "Would change";
    setStatus(
      verb + " " + (c.changed || 0) + " note(s); matched " + (c.matched || 0) +
      ", " + (c.unmatched_txns || 0) + " unmatched txns, " +
      (c.unmatched_orders || 0) + " unmatched orders.",
      "ok"
    );
  } catch (e) {
    setStatus(
      "Couldn't reach the bridge at " + settings.bridgeUrl +
      ". Is `amazon-sync-for-actual --serve` running?",
      "error"
    );
  }
}

async function activeTab() {
  var tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0];
}

function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

function isAmazon(tab) {
  try { return /(^|\.)amazon\./.test(new URL(tab.url || "http://x").hostname); }
  catch (e) { return false; }
}

// Ask the content script in `tabId` to scrape the current (rendered) page.
// Retries briefly so a freshly-navigated tab has time to inject + render.
async function scrapeTab(tabId, type) {
  for (var attempt = 0; attempt < 3; attempt++) {
    try {
      return await chrome.tabs.sendMessage(tabId, { type: type || "SCRAPE_PAGE" });
    } catch (e) {
      await sleep(700); // content script may not be ready yet
    }
  }
  throw new Error("content script unavailable");
}

// Navigate `tabId` to `url` and resolve once it has finished loading, OR after
// a timeout. The timeout is essential: navigations to old/empty year pages can
// redirect or be served from cache such that the "complete" event is missed —
// without a cap the whole walk would hang forever (this caused a freeze on an
// empty year). We resolve anyway and let the scrape's own render-wait handle it.
function navigate(tabId, url, timeoutMs) {
  return new Promise(function (resolve) {
    var done = false;
    function finish() {
      if (done) return;
      done = true;
      chrome.tabs.onUpdated.removeListener(listener);
      clearTimeout(timer);
      resolve();
    }
    function listener(id, info) {
      if (id === tabId && info.status === "complete") finish();
    }
    chrome.tabs.onUpdated.addListener(listener);
    var timer = setTimeout(finish, timeoutMs || 15000);
    try {
      chrome.tabs.update(tabId, { url: url });
    } catch (e) {
      finish(); // tab gone / invalid url — don't hang
    }
  });
}

var DELAY_BETWEEN_PAGES_MS = 900; // polite pause between navigations
var HARD_PAGE_CAP = 200;

// Single page (no navigation).
async function scanThisPage() {
  var tab = await activeTab();
  if (!tab || !isAmazon(tab)) return setStatus("Open your Amazon Orders page first.", "error");
  setStatus("Scanning…");
  try {
    var r = await scrapeTab(tab.id, "SCAN_PAGE");
    var found = (r && r.orders) || [];
    orders = ASFA.mergeOrders(orders, found);
    await save(); render();
    setStatus("Found " + found.length + " order(s); " + orders.length + " total.", "ok");
  } catch (e) {
    setStatus("Couldn't scan. Reload the Orders page and retry.", "error");
  }
}

// Walk every page of the *current* view by navigating the tab through the
// real next-page URLs (so Amazon renders each page) and scraping the live DOM.
// If `expectFilter` is given, the first page must report that active filter,
// otherwise we abort this period rather than silently re-scrape the default
// year (Amazon ignores an unknown time-filter param and keeps the default).
async function walkPages(tabId, startUrl, expectFilter) {
  var collected = [];
  var url = startUrl || null;       // null => start from current page
  var seen = {};
  for (var page = 1; page <= HARD_PAGE_CAP; page++) {
    if (url) { await navigate(tabId, url); await sleep(400); }
    var r;
    try { r = await scrapeTab(tabId, "SCRAPE_PAGE"); }
    catch (e) { break; }

    // Guard against silently re-scraping the default year: only abort if the
    // page reports a *different specific year* than requested. A missing/blank
    // activeFilter (old pages don't always echo it) is tolerated so we don't
    // wrongly skip a valid year.
    if (page === 1 && expectFilter && r && r.activeFilter) {
      var wantYear = /year-(\d{4})/.exec(expectFilter);
      var gotYear = /year-(\d{4})/.exec(r.activeFilter);
      if (wantYear && gotYear && wantYear[1] !== gotYear[1]) {
        setStatus("Skipping " + expectFilter + " (page showed " + r.activeFilter + ")…");
        return [];
      }
    }

    var found = (r && r.orders) || [];
    // An empty page means we've reached the end of this period (or it's an empty
    // year). Stop paging rather than chase a fallback startIndex forever — this
    // prevented a freeze when entering an old/empty year.
    if (!found.length) break;
    collected = ASFA.mergeOrders(collected, found);
    setStatus("Page " + page + " — " + collected.length + " orders so far…");

    var nextUrl = r && r.nextUrl;
    if (!nextUrl || seen[nextUrl]) break;
    seen[nextUrl] = true;
    url = nextUrl;
    await sleep(DELAY_BETWEEN_PAGES_MS);
  }
  return collected;
}

async function scanAllPages() {
  var tab = await activeTab();
  if (!tab || !isAmazon(tab)) return setStatus("Open your Amazon Orders page first.", "error");
  setStatus("Auto-walking pages…");
  try {
    var found = await walkPages(tab.id, null);
    orders = ASFA.mergeOrders(orders, found);
    await save(); render();
    setStatus("Collected " + found.length + " order(s) across pages; " + orders.length + " total.",
      "ok");
  } catch (e) {
    setStatus("Scan stopped: " + e.message, "error");
  }
}

async function scanEverything() {
  var tab = await activeTab();
  if (!tab || !isAmazon(tab)) return setStatus("Open your Amazon Orders page first.", "error");
  setStatus("Reading available years…");
  var filters;
  try {
    var fr = await scrapeTab(tab.id, "LIST_FILTERS");
    filters = (fr && fr.filters) || [];
  } catch (e) { filters = []; }

  try {
    if (!filters.length) {
      setStatus("No year filter found on this page; scanning current view only…");
      return scanAllPages();
    }
    // The rolling windows (last 30 days / 3 months) are subsets of the current
    // year, which we scan anyway — drop them to avoid redundant walks.
    var periods = ASFA.fullHistoryFilters(filters);
    var before = orders.length;
    for (var i = 0; i < periods.length; i++) {
      var startUrl = ASFA.applyTimeFilter(tab.url, periods[i].value);
      setStatus("Scanning " + periods[i].label + " (" + (i + 1) + "/" + periods.length + ")…");
      var found = await walkPages(tab.id, startUrl, periods[i].value);
      orders = ASFA.mergeOrders(orders, found);
      await save(); render();
    }
    setStatus("Done. Collected " + (orders.length - before) + " new order(s) across " +
      periods.length + " period(s); " + orders.length + " total.", "ok");
  } catch (e) {
    setStatus("Scan stopped: " + e.message, "error");
  }
}

function download(content, filename, mime) {
  var blob = new Blob([content], { type: mime });
  var url = URL.createObjectURL(blob);
  var a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
}

function today() { return new Date().toISOString().slice(0, 10); }

$("scan").addEventListener("click", scanThisPage);
$("scanall").addEventListener("click", scanAllPages);
$("scaneverything").addEventListener("click", scanEverything);
$("csv").addEventListener("click", function () {
  if (!orders.length) return setStatus("Nothing collected yet.");
  download(ASFA.ordersToCsv(orders), "amazon-orders-" + today() + ".csv", "text/csv");
  setStatus("CSV downloaded.");
});
$("json").addEventListener("click", function () {
  if (!orders.length) return setStatus("Nothing collected yet.");
  download(JSON.stringify(orders, null, 2), "amazon-orders-" + today() + ".json", "application/json");
  setStatus("JSON downloaded.");
});
$("clear").addEventListener("click", async function () {
  orders = [];
  await save();
  render();
  setStatus("Cleared.");
});

$("preview").addEventListener("click", function () { sendToBridge("/preview"); });
$("send").addEventListener("click", function () { sendToBridge("/sync"); });
$("toggle-settings").addEventListener("click", function () {
  var d = $("settings");
  d.open = !d.open;
});
$("save-settings").addEventListener("click", async function () {
  readSettingsFromForm();
  await chrome.storage.local.set({ settings: settings });
  setStatus("Settings saved.", "ok");
});

// ---- Diagnostics ---------------------------------------------------------
async function loadDiagnostics() {
  var data = await chrome.storage.local.get(["diagEnabled", "diagReports"]);
  $("diag-enabled").checked = data.diagEnabled !== false;
  renderDiagStats(data.diagReports || []);
}

function renderDiagStats(reports) {
  var pages = reports.filter(function (r) { return r && r.kind === "page"; }).length;
  var errs = reports.filter(function (r) { return r && r.kind === "error"; }).length;
  $("diag-stats").textContent = reports.length
    ? (reports.length + " record(s): " + pages + " page(s), " + errs + " error(s).")
    : "No diagnostics captured yet.";
}

async function getReports() {
  var data = await chrome.storage.local.get("diagReports");
  return data.diagReports || [];
}

$("diag-enabled").addEventListener("change", async function () {
  await chrome.storage.local.set({ diagEnabled: $("diag-enabled").checked });
  setStatus($("diag-enabled").checked ? "Diagnostics on." : "Diagnostics off.", "ok");
});

$("diag-download").addEventListener("click", async function () {
  var reports = await getReports();
  if (!reports.length) return setStatus("No diagnostics captured yet.", "error");
  var summary = ASFA_DIAG.summarizeReports(reports);
  var payload = { summary: summary, reports: reports };
  download(JSON.stringify(payload, null, 2),
    "asfa-diagnostics-" + today() + ".json", "application/json");
  setStatus("Diagnostics report downloaded.", "ok");
});

$("diag-preview").addEventListener("click", async function () {
  var reports = await getReports();
  var out = $("diag-out");
  if (!reports.length) { out.hidden = true; return setStatus("No diagnostics yet.", "error"); }
  out.textContent = JSON.stringify(ASFA_DIAG.summarizeReports(reports), null, 2);
  out.hidden = false;
});

$("diag-clear").addEventListener("click", async function () {
  await chrome.storage.local.set({ diagReports: [] });
  $("diag-out").hidden = true;
  renderDiagStats([]);
  setStatus("Diagnostics cleared.", "ok");
});

load();
loadDiagnostics();
