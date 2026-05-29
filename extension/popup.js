/* Popup logic: talk to the content script, accumulate orders, export CSV/JSON. */
"use strict";

var orders = [];

function $(id) { return document.getElementById(id); }

function setStatus(msg) { $("status").textContent = msg || ""; }

function render() {
  $("count").textContent = orders.length;
  $("items").textContent = orders.reduce(function (n, o) {
    return n + (o.items ? o.items.length : 0);
  }, 0);
}

async function load() {
  var data = await chrome.storage.local.get("orders");
  orders = data.orders || [];
  render();
}

async function save() {
  await chrome.storage.local.set({ orders: orders });
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

load();
