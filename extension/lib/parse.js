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

  // A calendar year is "plausible" for an Amazon order: not the Unix epoch / a
  // mis-parse, and not the far future. Cards without a real order date (e.g. the
  // "Alexa+" subscription) otherwise collapsed to 1970-01-01.
  function plausibleYear(y) {
    var now = new Date().getFullYear();
    return y >= 2000 && y <= now + 1;
  }

  // Normalise a date string to YYYY-MM-DD when possible, else return it trimmed.
  // Returns "" for implausible parses (epoch/garbage) rather than a bogus date.
  function normalizeDate(value) {
    if (!value) return "";
    var s = String(value).trim();
    var iso = s.match(/\b(\d{4})-(\d{2})-(\d{2})\b/);
    if (iso) return plausibleYear(parseInt(iso[1], 10)) ? (iso[1] + "-" + iso[2] + "-" + iso[3]) : "";
    var t = Date.parse(s);
    if (!isNaN(t)) {
      var d = new Date(t);
      if (!plausibleYear(d.getFullYear())) return "";
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

  // Pagination: Amazon order list pages step `startIndex` by a page size (10).
  // Rather than guess, we read the actual "Next" link's startIndex when present
  // and otherwise fall back to current + pageSize. Returns null when there is no
  // next page (so the walker can stop cleanly).
  function nextStartIndex(doc, currentStart, pageSize) {
    pageSize = pageSize || 10;
    currentStart = currentStart || 0;

    function startIndexFromHref(href) {
      if (!href) return null;
      var m = String(href).match(/[?&]startIndex=(\d+)/);
      return m ? parseInt(m[1], 10) : null;
    }

    if (doc && doc.querySelectorAll) {
      // Prefer an explicit, non-disabled "Next" pagination control.
      var sels = [
        ".a-pagination li.a-last:not(.a-disabled) a",
        "ul.a-pagination .a-last:not(.a-disabled) a",
        "a.a-last",
        '[class*="pagination"] a[href*="startIndex"]'
      ];
      for (var s = 0; s < sels.length; s++) {
        var nodes = doc.querySelectorAll(sels[s]);
        for (var i = 0; i < nodes.length; i++) {
          var si = startIndexFromHref(nodes[i].getAttribute("href"));
          if (si !== null && si > currentStart) return si;
        }
      }
      // If a disabled "last" element exists, we are on the final page.
      if (doc.querySelector(".a-pagination li.a-last.a-disabled, .a-last.a-disabled")) {
        return null;
      }
      // No pagination markup at all: only guess "next page" when this page is
      // FULL (>= pageSize order cards). A short/empty page is the last one, so
      // return null — this avoids paging forever past an empty/old year.
      var cardCount = (doc.querySelectorAll(".order-card, .js-order-card") || []).length;
      if (cardCount < pageSize) return null;
    }
    return currentStart + pageSize;
  }

  // Discover the available time filters (years / "last 3 months") from the
  // orders page, so a full scan can walk each one. Works regardless of how the
  // dropdown is rendered: reads native <option> values AND any links/elements
  // carrying a timeFilter=/orderFilter= value. Returns de-duplicated
  // {label, value}. ``value`` is the filter token (e.g. "year-2024").
  var TIME_FILTER_RE = /^(year-\d{4}|months-\d+|last30|archived)$/;

  function findTimeFilters(doc) {
    var out = [];
    var seen = {};
    if (!doc || !doc.querySelectorAll) return out;

    function add(value, label) {
      value = (value || "").trim();
      if (!value || seen[value] || !TIME_FILTER_RE.test(value)) return;
      seen[value] = true;
      out.push({ label: (label || value).replace(/\s+/g, " ").trim(), value: value });
    }

    // 1. Native <option> elements (covers <select name="timeFilter"/"orderFilter">).
    var opts = doc.querySelectorAll("option");
    for (var i = 0; i < opts.length; i++) {
      add(opts[i].getAttribute("value"), opts[i].textContent);
    }
    // 2. Links / elements whose href or data carries the filter token (covers
    //    custom, non-<select> dropdowns rendered as menus).
    var links = doc.querySelectorAll(
      'a[href*="timeFilter="], a[href*="orderFilter="], [data-value]'
    );
    for (var j = 0; j < links.length; j++) {
      var href = links[j].getAttribute("href") || "";
      var m = href.match(/(?:timeFilter|orderFilter)=([^&]+)/);
      var val = m ? decodeURIComponent(m[1]) : (links[j].getAttribute("data-value") || "");
      add(val, links[j].textContent);
    }

    // Stable, useful order: rolling windows first, then years newest-first.
    out.sort(function (a, b) {
      var ay = a.value.match(/year-(\d{4})/), by = b.value.match(/year-(\d{4})/);
      if (ay && by) return parseInt(by[1], 10) - parseInt(ay[1], 10);
      if (ay && !by) return 1;            // years after windows
      if (!ay && by) return -1;
      return 0;
    });
    return out;
  }

  // Periods to scan for a *full history* run. The rolling windows (last 30 days,
  // last 3 months, etc.) are strict subsets of the current year, so the year
  // buckets already cover them — drop them to avoid redundant page walks. Keeps
  // every year-NNNN bucket plus "archived"; falls back to all filters if there
  // are somehow no year buckets (so we never scan nothing).
  function fullHistoryFilters(filters) {
    var kept = (filters || []).filter(function (f) {
      return /^year-\d{4}$/.test(f.value) || f.value === "archived";
    });
    return kept.length ? kept : (filters || []);
  }

  // Set every known time-filter query parameter on a URL so it works on both the
  // modern (/your-orders, "timeFilter") and legacy (/gp/css/order-history,
  // "orderFilter") order pages.
  function applyTimeFilter(urlStr, value) {
    var u = new URL(urlStr);
    u.searchParams.set("timeFilter", value);
    u.searchParams.set("orderFilter", value);
    u.searchParams.set("startIndex", "0");
    return u.toString();
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

  // Summarize collected orders by calendar year: count, summed total (cents),
  // and item count. Orders with no/!parseable date are bucketed under "unknown".
  // Returns rows sorted newest-year-first, with "unknown" last, plus a totals row.
  function summarizeOrdersByYear(orders) {
    var byYear = {};
    (orders || []).forEach(function (o) {
      var d = normalizeDate(o.orderDate);
      var year = /^\d{4}-/.test(d) ? d.slice(0, 4) : "unknown";
      var bucket = byYear[year] || (byYear[year] = { year: year, orders: 0, items: 0, totalCents: 0 });
      bucket.orders += 1;
      bucket.items += (o.items && o.items.length) || 0;
      if (o.orderTotalCents != null) bucket.totalCents += o.orderTotalCents;
    });
    var rows = Object.keys(byYear).map(function (y) { return byYear[y]; });
    rows.sort(function (a, b) {
      if (a.year === "unknown") return 1;
      if (b.year === "unknown") return -1;
      return b.year < a.year ? -1 : (b.year > a.year ? 1 : 0); // newest first
    });
    var totals = rows.reduce(function (acc, r) {
      acc.orders += r.orders; acc.items += r.items; acc.totalCents += r.totalCents;
      return acc;
    }, { year: "all", orders: 0, items: 0, totalCents: 0 });
    return { rows: rows, totals: totals };
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
    summarizeOrdersByYear: summarizeOrdersByYear,
    nextStartIndex: nextStartIndex,
    findTimeFilters: findTimeFilters,
    fullHistoryFilters: fullHistoryFilters,
    applyTimeFilter: applyTimeFilter,
    buildBridgeOptions: buildBridgeOptions
  };

  if (typeof module !== "undefined" && module.exports) module.exports = ASFA;
  if (root) root.ASFA = ASFA;
})(typeof globalThis !== "undefined" ? globalThis : this);
