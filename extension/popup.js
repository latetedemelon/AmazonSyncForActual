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

function render() {
  $("count").textContent = orders.length;
  $("items").textContent = orders.reduce(function (n, o) {
    return n + (o.items ? o.items.length : 0);
  }, 0);
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

async function scan(type, maxPages) {
  var tab = await activeTab();
  if (!tab || !/(^|\.)amazon\./.test(new URL(tab.url || "http://x").hostname)) {
    setStatus("Open your Amazon Orders page first.");
    return;
  }
  setStatus("Scanning…");
  try {
    var resp = await chrome.tabs.sendMessage(tab.id, { type: type, maxPages: maxPages });
    var found = (resp && resp.orders) || [];
    orders = ASFA.mergeOrders(orders, found);
    await save();
    render();
    setStatus("Found " + found.length + " order(s) this scan; " + orders.length + " total.");
  } catch (e) {
    setStatus("Couldn't scan. Make sure you're on the Orders page and reload it, then retry.");
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

$("scan").addEventListener("click", function () { scan("SCAN_PAGE"); });
$("scanmore").addEventListener("click", function () { scan("SCAN_PAGES", 6); });
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
