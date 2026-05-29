/*
 * Redacted, local-first diagnostics for the extractor.
 *
 * The point of this module is to make extraction problems *actionable* without
 * ever capturing personal data. As you browse order pages the content script
 * records how well extraction worked -- which card selector matched, how many
 * orders/fields it recovered, and where it failed -- and these helpers redact
 * everything sensitive:
 *
 *   - money/date *values* are reduced to a "shape" (digits -> #, letters -> x/X,
 *     punctuation/currency symbols kept): "$1,234.56" -> "$#,###.##". This tells
 *     us the FORMAT (great for fixing the parser) but not the amount.
 *   - product names, order ids, addresses and names are never stored; only
 *     counts, coverage ratios and CSS class names (which are app chrome, not
 *     personal) are kept.
 *
 * Pure and DOM-light, so it runs in the content script, the popup and
 * `node --test` alike.
 */
(function (root) {
  "use strict";

  var SCHEMA_VERSION = 1;

  // Reduce a string to its character "shape": preserves structure (separators,
  // currency symbols, case) while masking the actual digits and letters.
  function shapeOf(value, maxLen) {
    if (value === null || value === undefined) return "";
    var s = String(value);
    if (maxLen && s.length > maxLen) s = s.slice(0, maxLen) + "…";
    var out = "";
    for (var i = 0; i < s.length; i++) {
      var ch = s[i];
      if (ch >= "0" && ch <= "9") out += "#";
      else if (ch >= "A" && ch <= "Z") out += "X";
      else if (ch >= "a" && ch <= "z") out += "x";
      else if (/[À-ÿ]/.test(ch)) out += "x";   // accented letters -> x
      else out += ch;                            // separators, $, £, €, etc.
    }
    return out;
  }

  // Scrub free text (e.g. an error message) of anything identifying.
  function redactText(value, maxLen) {
    var s = String(value === null || value === undefined ? "" : value);
    s = s.replace(/https?:\/\/[^\s)]+/gi, "<url>");
    s = s.replace(/\b\d{3}-\d{7}-\d{7}\b/g, "<orderid>");
    s = s.replace(/\d{2,}/g, function (m) { return new Array(m.length + 1).join("#"); });
    if (maxLen && s.length > maxLen) s = s.slice(0, maxLen) + "…";
    return s;
  }

  // Classify a URL path (no query string is ever read) into a coarse page kind.
  function pathKind(path) {
    var p = String(path || "").toLowerCase();
    if (p.indexOf("your-orders") !== -1) return "your-orders";
    if (p.indexOf("order-history") !== -1) return "order-history";
    if (p.indexOf("/summary/print") !== -1 || p.indexOf("/print.html") !== -1) return "invoice";
    if (p.indexOf("order-details") !== -1 || p.indexOf("/order/") !== -1) return "order-details";
    return "other";
  }

  function classListOf(el) {
    if (!el) return [];
    if (el.classList && el.classList.length) return Array.prototype.slice.call(el.classList);
    var cn = el.className;
    if (cn && typeof cn === "object" && "baseVal" in cn) cn = cn.baseVal; // SVG
    if (!cn || typeof cn !== "string") return [];
    return cn.split(/\s+/).filter(Boolean);
  }

  // Gather unique class tokens (on el and its descendants) that match `re`.
  // CSS class names are app chrome, not personal data, and are the single most
  // actionable hint for repairing selectors.
  function collectMatchingClasses(el, re, max) {
    var seen = {};
    var out = [];
    function add(tokens) {
      for (var i = 0; i < tokens.length; i++) {
        var t = tokens[i];
        if (re.test(t) && !seen[t]) {
          seen[t] = true;
          out.push(t);
          if (out.length >= (max || 20)) return true;
        }
      }
      return false;
    }
    if (add(classListOf(el))) return out;
    if (el && el.querySelectorAll) {
      var nodes = el.querySelectorAll("*");
      for (var i = 0; i < nodes.length; i++) {
        if (add(classListOf(nodes[i]))) break;
      }
    }
    return out;
  }

  // Append to a capped ring buffer (returns a new array).
  function ringPush(arr, item, cap) {
    var next = (arr || []).slice();
    next.push(item);
    cap = cap || 200;
    if (next.length > cap) next = next.slice(next.length - cap);
    return next;
  }

  function _ctxKey(r) { return (r.host || "?") + "|" + (r.pathKind || "?"); }
  function _rate(num, den) { return den ? Math.round((num / den) * 1000) / 1000 : null; }

  // Aggregate many per-page records into one actionable summary object. This is
  // also exactly what gets handed over for review.
  function summarizeReports(reports) {
    reports = reports || [];
    var byContext = {};
    var failurePatterns = {};
    var errorCounts = {};
    var pages = 0, errors = 0;
    var totals = { cards: 0, orders: 0, orderId: 0, orderDate: 0, orderTotal: 0, items: 0 };

    reports.forEach(function (r) {
      if (!r) return;
      if (r.kind === "error") {
        errors++;
        var ekey = (r.error && r.error.name || "Error") + ": " + (r.error && r.error.message || "");
        errorCounts[ekey] = (errorCounts[ekey] || 0) + 1;
        return;
      }
      pages++;
      var key = _ctxKey(r);
      var c = byContext[key] || (byContext[key] = {
        host: r.host, pathKind: r.pathKind, pages: 0, cards: 0, orders: 0,
        field: { orderId: 0, orderDate: 0, orderTotal: 0, items: 0 },
        cardSelectors: {}
      });
      var cov = r.coverage || {};
      c.pages++;
      c.cards += cov.cards || 0;
      c.orders += r.ordersExtracted || 0;
      c.field.orderId += cov.orderId || 0;
      c.field.orderDate += cov.orderDate || 0;
      c.field.orderTotal += cov.orderTotal || 0;
      c.field.items += cov.items || 0;
      if (r.cardSelectorUsed) {
        c.cardSelectors[r.cardSelectorUsed] = (c.cardSelectors[r.cardSelectorUsed] || 0) + 1;
      }

      totals.cards += cov.cards || 0;
      totals.orders += r.ordersExtracted || 0;
      totals.orderId += cov.orderId || 0;
      totals.orderDate += cov.orderDate || 0;
      totals.orderTotal += cov.orderTotal || 0;
      totals.items += cov.items || 0;

      (r.fieldFailures || []).forEach(function (f) {
        var sig = (f.missing || []).slice().sort().join("+") +
          " @ [" + (f.classes || []).slice(0, 6).join(",") + "]";
        var fp = failurePatterns[sig] || (failurePatterns[sig] = {
          signature: sig, count: 0, missing: (f.missing || []).slice(),
          sampleShapes: { total: f.totalShape || "", date: f.dateShape || "" },
          contexts: {}
        });
        fp.count++;
        fp.contexts[key] = (fp.contexts[key] || 0) + 1;
      });
    });

    function ctxRates(c) {
      return {
        host: c.host, pathKind: c.pathKind, pages: c.pages, cards: c.cards, orders: c.orders,
        coverageRate: {
          orderId: _rate(c.field.orderId, c.cards),
          orderDate: _rate(c.field.orderDate, c.cards),
          orderTotal: _rate(c.field.orderTotal, c.cards),
          items: _rate(c.field.items, c.cards)
        },
        cardSelectors: c.cardSelectors
      };
    }

    return {
      v: SCHEMA_VERSION,
      generatedAt: new Date().toISOString(),
      totalReports: reports.length,
      pages: pages,
      errors: errors,
      health: {
        cards: totals.cards,
        orders: totals.orders,
        orderExtractionRate: _rate(totals.orders, totals.cards),
        coverageRate: {
          orderId: _rate(totals.orderId, totals.cards),
          orderDate: _rate(totals.orderDate, totals.cards),
          orderTotal: _rate(totals.orderTotal, totals.cards),
          items: _rate(totals.items, totals.cards)
        }
      },
      byContext: Object.keys(byContext).map(function (k) { return ctxRates(byContext[k]); }),
      failurePatterns: Object.keys(failurePatterns)
        .map(function (k) { return failurePatterns[k]; })
        .sort(function (a, b) { return b.count - a.count; })
        .slice(0, 12),
      errorCounts: Object.keys(errorCounts)
        .map(function (k) { return { error: k, count: errorCounts[k] }; })
        .sort(function (a, b) { return b.count - a.count; })
        .slice(0, 12)
    };
  }

  var DIAG = {
    SCHEMA_VERSION: SCHEMA_VERSION,
    shapeOf: shapeOf,
    redactText: redactText,
    pathKind: pathKind,
    classListOf: classListOf,
    collectMatchingClasses: collectMatchingClasses,
    ringPush: ringPush,
    summarizeReports: summarizeReports
  };

  if (typeof module !== "undefined" && module.exports) module.exports = DIAG;
  if (root) root.ASFA_DIAG = DIAG;
})(typeof globalThis !== "undefined" ? globalThis : this);
