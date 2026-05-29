/*
 * Content script: extracts orders from an Amazon "Your Orders" page.
 *
 * Amazon's order pages share the same structure and CSS classes across all
 * marketplaces (the front-end is one codebase), so a single defensive
 * extractor works for amazon.com, .ca, .co.uk, .com.au, .in, .sg, .ie, .ae,
 * .co.za, etc. Labels are matched in English plus French (for amazon.ca) and a
 * few other languages as a bonus.
 *
 * Selectors are best-effort and may need updates as Amazon changes its markup;
 * `extractOrdersFromDocument` is exported for jsdom-based unit tests.
 */
(function () {
  "use strict";

  var ASFA = (typeof module !== "undefined" && module.exports)
    ? require("./lib/parse.js")
    : globalThis.ASFA;

  var ORDER_ID_RE = /\b\d{3}-\d{7}-\d{7}\b/;
  var ASIN_RE = /\/(?:dp|gp\/product|product)\/([A-Z0-9]{10})/i;
  var PRODUCT_HREF_RE = /\/(?:dp|gp\/product|product)\//;

  // Label regexes (English + fr/de/es as a bonus). Anchored-ish so "Total"
  // doesn't swallow unrelated text.
  var LABEL_DATE = /\b(order placed|order date|commande(?: pass[ée]e| effectu[ée]e)?|bestellung aufgegeben|pedido realizado|data dell'ordine)\b/i;
  var LABEL_TOTAL = /^\s*(total|grand total|order total|montant total|total de la commande|gesamtsumme|total del pedido|totale)\s*[:.]?\s*$/i;

  var CARD_SELECTORS = [
    ".order-card.js-order-card",
    "li.order-card__list-item",
    ".js-order-card",
    ".order-card",
    ".a-box-group.order",
    ".order"
  ];

  function text(el) {
    return el && el.textContent ? el.textContent.replace(/\s+/g, " ").trim() : "";
  }

  function findOrderCards(doc) {
    for (var i = 0; i < CARD_SELECTORS.length; i++) {
      var els = doc.querySelectorAll(CARD_SELECTORS[i]);
      if (els && els.length) return Array.prototype.slice.call(els);
    }
    return [];
  }

  function valueNear(labelEl) {
    // 1. A dedicated value child inside the same element.
    if (labelEl.querySelector) {
      var child = labelEl.querySelector('.value, [class*="value"]');
      if (child && child !== labelEl) {
        var ct = text(child);
        if (ct) return ct;
      }
    }
    // 2. The next sibling element (classic label / value pair).
    var sib = labelEl.nextElementSibling;
    if (sib) {
      var t = text(sib);
      if (t) return t;
    }
    // 3. Whatever remains of the parent's text after the label.
    var parent = labelEl.parentElement;
    if (parent) {
      var cand = parent.querySelector('.value, .a-size-base, [class*="value"]');
      if (cand && cand !== labelEl) {
        var cvt = text(cand);
        if (cvt) return cvt;
      }
      var rest = text(parent).replace(text(labelEl), "").trim();
      if (rest) return rest;
    }
    return null;
  }

  function findLabeledValue(card, labelRe) {
    var els = card.querySelectorAll('span, div, dt, th, h5, .a-color-secondary');
    var matches = [];
    for (var i = 0; i < els.length; i++) {
      var t = text(els[i]);
      if (!t || t.length > 60) continue;
      if (!labelRe.test(t)) continue;
      matches.push(els[i]);
    }
    // Prefer the most specific (shortest-text) label element, so a bare
    // "Order placed" span wins over the whole column that contains it.
    matches.sort(function (a, b) { return text(a).length - text(b).length; });
    for (var j = 0; j < matches.length; j++) {
      var v = valueNear(matches[j]);
      if (v) return v;
    }
    return null;
  }

  function findFirstDate(card) {
    var t = text(card);
    var m = t.match(/\b\d{4}-\d{2}-\d{2}\b/) ||
      t.match(/\b\d{1,2}\s+[A-Za-zÀ-ÿ]{3,}\.?\s+\d{4}\b/) ||
      t.match(/\b[A-Za-zÀ-ÿ]{3,}\.?\s+\d{1,2},?\s+\d{4}\b/);
    return m ? m[0] : "";
  }

  function extractAsin(href) {
    var m = (href || "").match(ASIN_RE);
    return m ? m[1].toUpperCase() : null;
  }

  function extractOrderId(card) {
    var byText = text(card).match(ORDER_ID_RE);
    if (byText) return byText[0];
    var links = card.querySelectorAll('a[href]');
    for (var i = 0; i < links.length; i++) {
      var href = links[i].getAttribute("href") || "";
      var m = href.match(/order(?:ID|Id|_id)=([0-9-]+)/i);
      if (m) return m[1];
    }
    return "";
  }

  function extractQty(container) {
    var q = container.querySelector(
      '.item-view-qty, .product-image__qty, .od-item-view-qty, [data-quantity], .quantity'
    );
    if (q) {
      var raw = (q.getAttribute && q.getAttribute("data-quantity")) || text(q);
      var m = String(raw).match(/\d+/);
      if (m) return Math.max(1, parseInt(m[0], 10));
    }
    var t = text(container);
    var qm = t.match(/\bqty[:\s]*?(\d+)/i) || t.match(/\b(\d+)\s+of\b/i);
    if (qm) return Math.max(1, parseInt(qm[1], 10));
    return 1;
  }

  function extractItems(card) {
    var links = card.querySelectorAll('a[href]');
    var items = [];
    var seen = {};
    for (var i = 0; i < links.length; i++) {
      var href = links[i].getAttribute("href") || "";
      if (!PRODUCT_HREF_RE.test(href)) continue;
      var name = text(links[i]);
      if (!name) continue;
      var asin = extractAsin(href);
      var id = asin || name;
      if (seen[id]) continue;
      seen[id] = true;
      var container = (links[i].closest && links[i].closest(
        '.yohtmlc-item, .a-fixed-left-grid, .item-box, .a-fixed-left-grid-inner, .shipment, .delivery-box'
      )) || card;
      var priceEl = container.querySelector('.a-price .a-offscreen, [class*="price"]');
      items.push({
        name: name,
        quantity: extractQty(container),
        unitPriceCents: priceEl ? ASFA.parseMoneyToCents(text(priceEl)) : null,
        totalCents: null,
        asin: asin,
        shipDate: null
      });
    }
    return items;
  }

  function extractOrderFromCard(card, currency) {
    var totalStr = findLabeledValue(card, LABEL_TOTAL);
    var dateStr = findLabeledValue(card, LABEL_DATE) || findFirstDate(card);
    return {
      orderId: extractOrderId(card),
      orderDate: dateStr ? ASFA.normalizeDate(dateStr) : "",
      orderTotalCents: totalStr != null ? ASFA.parseMoneyToCents(totalStr) : null,
      currency: currency || "USD",
      items: extractItems(card)
    };
  }

  function extractOrdersFromDocument(doc, opts) {
    opts = opts || {};
    var host = opts.host ||
      (doc && doc.location && doc.location.hostname) ||
      (typeof location !== "undefined" ? location.hostname : "");
    var currency = opts.currency || ASFA.currencyForHost(host);

    var orders = [];
    findOrderCards(doc).forEach(function (card) {
      var order = extractOrderFromCard(card, currency);
      if (order.items.length || order.orderTotalCents != null) orders.push(order);
    });
    return ASFA.mergeOrders(orders);
  }

  // ---- Multi-page scan (browser only) ----------------------------------
  async function scanPages(maxPages) {
    var all = extractOrdersFromDocument(document);
    var base = new URL(location.href);
    var start = parseInt(base.searchParams.get("startIndex") || "0", 10);
    for (var p = 1; p < (maxPages || 1); p++) {
      start += 10;
      base.searchParams.set("startIndex", String(start));
      var doc;
      try {
        var resp = await fetch(base.toString(), { credentials: "include" });
        if (!resp.ok) break;
        var html = await resp.text();
        doc = new DOMParser().parseFromString(html, "text/html");
      } catch (e) {
        break;
      }
      var orders = extractOrdersFromDocument(doc);
      if (!orders.length) break;
      all = ASFA.mergeOrders(all, orders);
    }
    return all;
  }

  // ---- Messaging (browser only) ----------------------------------------
  if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
      if (!msg) return;
      if (msg.type === "SCAN_PAGE") {
        sendResponse({ orders: extractOrdersFromDocument(document) });
        return true;
      }
      if (msg.type === "SCAN_PAGES") {
        scanPages(msg.maxPages || 5).then(function (orders) {
          sendResponse({ orders: orders });
        });
        return true; // async response
      }
    });
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      extractOrdersFromDocument: extractOrdersFromDocument,
      extractOrderFromCard: extractOrderFromCard,
      findLabeledValue: findLabeledValue,
      extractItems: extractItems,
      extractOrderId: extractOrderId,
      extractAsin: extractAsin
    };
  }
})();
