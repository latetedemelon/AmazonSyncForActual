/*
 * Pure helpers shared by the content script, popup and Node tests.
 *
 * No DOM or extension APIs are touched here so the file can be `require()`d in
 * `node --test`. It is exposed both as a CommonJS module (Node) and on
 * `globalThis.ASFA` (browser content-script / popup), with no bundler needed.
 */
(function (root) {
  "use strict";

  // Amazon marketplace host -> default currency. Used to tag exported rows so
  // the Python importer / Actual matching stays within one currency. English
  // first-language marketplaces are marked; others are included for free.
  var CURRENCY_BY_HOST = {
    "amazon.com": "USD",        // US (English)
    "amazon.ca": "CAD",         // Canada (English/French)
    "amazon.co.uk": "GBP",      // UK (English)
    "amazon.com.au": "AUD",     // Australia (English); also serves NZ
    "amazon.in": "INR",         // India (English)
    "amazon.sg": "SGD",         // Singapore (English)
    "amazon.ie": "EUR",         // Ireland (English)
    "amazon.ae": "AED",         // UAE (English)
    "amazon.co.za": "ZAR",      // South Africa (English)
    // Non-English marketplaces (still handled if you use them):
    "amazon.com.mx": "MXN",
    "amazon.com.br": "BRL",
    "amazon.de": "EUR",
    "amazon.fr": "EUR",
    "amazon.es": "EUR",
    "amazon.it": "EUR",
    "amazon.nl": "EUR",
    "amazon.com.be": "EUR",
    "amazon.se": "SEK",
    "amazon.pl": "PLN",
    "amazon.com.tr": "TRY",
    "amazon.co.jp": "JPY",
    "amazon.sa": "SAR",
    "amazon.eg": "EGP"
  };

  function currencyForHost(host) {
    if (!host) return "USD";
    host = String(host).toLowerCase().replace(/^www\./, "");
    if (CURRENCY_BY_HOST[host]) return CURRENCY_BY_HOST[host];
    // Match the longest known suffix (handles smile.amazon.*, regional subdomains).
    var best = null;
    Object.keys(CURRENCY_BY_HOST).forEach(function (known) {
      if (host === known || host.endsWith("." + known)) {
        if (!best || known.length > best.length) best = known;
      }
    });
    return best ? CURRENCY_BY_HOST[best] : "USD";
  }

  // Parse a messy money string into integer minor units (cents). Mirrors the
  // Python money parser so the two stay consistent: handles symbols/letters,
  // thousands separators, comma decimals ("19,99"), and parenthesised credits.
  function parseMoneyToCents(value) {
    if (value === null || value === undefined) return null;
    var s = String(value).trim();
    if (!s) return null;

    var negative = false;
    if (s.charAt(0) === "(" && s.charAt(s.length - 1) === ")") {
      negative = true;
      s = s.slice(1, -1);
    }
    s = s.replace(/[^0-9.,-]/g, "");
    if ((s.match(/-/g) || []).length > 1) return null;
    if (s.charAt(0) === "-") {
      negative = !negative;
      s = s.slice(1);
    }
    if (!s || s === "." || s === ",") return null;

    if (s.indexOf(",") !== -1 && s.indexOf(".") !== -1) {
      if (s.lastIndexOf(",") > s.lastIndexOf(".")) {
        s = s.replace(/\./g, "").replace(",", ".");  // 1.234,56 -> 1234.56
      } else {
        s = s.replace(/,/g, "");                       // 1,234.56 -> 1234.56
      }
    } else if (s.indexOf(",") !== -1) {
      var parts = s.split(",");
      if (parts.length === 2 && (parts[1].length === 1 || parts[1].length === 2)) {
        s = s.replace(",", ".");                        // 19,99 -> 19.99
      } else {
        s = s.replace(/,/g, "");                        // 1,234 -> 1234
      }
    }

    var num = Number(s);
    if (!isFinite(num)) return null;
    var cents = Math.round(num * 100);
    return negative ? -cents : cents;
  }

  function centsToAmountString(cents) {
    if (cents === null || cents === undefined) return "";
    var sign = cents < 0 ? "-" : "";
    var c = Math.abs(Math.round(cents));
    return sign + Math.floor(c / 100) + "." + String(c % 100).padStart(2, "0");
  }

  function parseQuantity(value) {
    if (!value) return 1;
    var m = String(value).match(/\d+/);
    if (!m) return 1;
    var n = parseInt(m[0], 10);
    return n > 0 ? n : 1;
  }

  // Normalise a date string to YYYY-MM-DD when possible, else return it trimmed.
  function normalizeDate(value) {
    if (!value) return "";
    var s = String(value).trim();
    var iso = s.match(/\b(\d{4})-(\d{2})-(\d{2})\b/);
    if (iso) return iso[1] + "-" + iso[2] + "-" + iso[3];
    var t = Date.parse(s);
    if (!isNaN(t)) {
      var d = new Date(t);
      var mo = String(d.getMonth() + 1).padStart(2, "0");
      var da = String(d.getDate()).padStart(2, "0");
      return d.getFullYear() + "-" + mo + "-" + da;
    }
    return s;
  }

  var CSV_HEADERS = [
    "Order ID", "Order Date", "Ship Date", "Product Name", "Quantity",
    "Unit Price", "Total Owed", "Order Total", "ASIN", "Currency"
  ];

  function csvEscape(v) {
    v = v === null || v === undefined ? "" : String(v);
    return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  }

  // Render orders as a CSV whose headers exactly match the Python importer.
  function ordersToCsv(orders) {
    var rows = [CSV_HEADERS.join(",")];
    (orders || []).forEach(function (order) {
      var orderDate = normalizeDate(order.orderDate);
      var orderTotal = order.orderTotalCents != null
        ? centsToAmountString(order.orderTotalCents) : "";
      var currency = order.currency || "USD";
      var items = (order.items && order.items.length)
        ? order.items : [{ name: "", quantity: 1 }];
      items.forEach(function (item) {
        rows.push([
          csvEscape(order.orderId || ""),
          csvEscape(orderDate),
          csvEscape(normalizeDate(item.shipDate || "")),
          csvEscape(item.name || ""),
          csvEscape(item.quantity || 1),
          csvEscape(item.unitPriceCents != null ? centsToAmountString(item.unitPriceCents) : ""),
          csvEscape(item.totalCents != null ? centsToAmountString(item.totalCents) : ""),
          csvEscape(orderTotal),
          csvEscape(item.asin || ""),
          csvEscape(currency)
        ].join(","));
      });
    });
    return rows.join("\n") + "\n";
  }

  // Combine order lists, de-duplicating by order id (and items by ASIN/name) so
  // repeated scans / multi-page scans accumulate cleanly.
  function mergeOrders() {
    var map = new Map();
    var orderKeys = [];
    for (var a = 0; a < arguments.length; a++) {
      var list = arguments[a] || [];
      for (var i = 0; i < list.length; i++) {
        var o = list[i];
        var key = o.orderId || (o.orderDate + "|" + o.orderTotalCents);
        if (!map.has(key)) {
          map.set(key, {
            orderId: o.orderId || "",
            orderDate: o.orderDate || "",
            orderTotalCents: o.orderTotalCents != null ? o.orderTotalCents : null,
            currency: o.currency || "USD",
            items: []
          });
          orderKeys.push(key);
        }
        var dst = map.get(key);
        if (!dst.orderDate && o.orderDate) dst.orderDate = o.orderDate;
        if (dst.orderTotalCents == null && o.orderTotalCents != null) dst.orderTotalCents = o.orderTotalCents;
        if (o.currency) dst.currency = o.currency;
        var seen = new Set(dst.items.map(function (it) { return it.asin || it.name; }));
        (o.items || []).forEach(function (it) {
          var id = it.asin || it.name;
          if (id && seen.has(id)) return;
          if (id) seen.add(id);
          dst.items.push(it);
        });
      }
    }
    return orderKeys.map(function (k) { return map.get(k); });
  }

  // Build the option overrides sent to the bridge from popup settings. Only
  // non-empty values are included so the server keeps its own defaults.
  function buildBridgeOptions(settings) {
    settings = settings || {};
    var opts = {};
    if (settings.noteMode) opts.note_mode = settings.noteMode;
    if (settings.account) opts.account = settings.account;
    if (settings.days !== "" && settings.days !== undefined && settings.days !== null) {
      var d = parseInt(settings.days, 10);
      if (!isNaN(d)) opts.days = d;
    }
    return opts;
  }

  var ASFA = {
    CURRENCY_BY_HOST: CURRENCY_BY_HOST,
    currencyForHost: currencyForHost,
    parseMoneyToCents: parseMoneyToCents,
    centsToAmountString: centsToAmountString,
    parseQuantity: parseQuantity,
    normalizeDate: normalizeDate,
    CSV_HEADERS: CSV_HEADERS,
    csvEscape: csvEscape,
    ordersToCsv: ordersToCsv,
    mergeOrders: mergeOrders,
    buildBridgeOptions: buildBridgeOptions
  };

  if (typeof module !== "undefined" && module.exports) module.exports = ASFA;
  if (root) root.ASFA = ASFA;
})(typeof globalThis !== "undefined" ? globalThis : this);
