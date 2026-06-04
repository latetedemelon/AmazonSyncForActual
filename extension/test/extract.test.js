"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

let JSDOM = null;
try {
  ({ JSDOM } = require("jsdom"));
} catch (e) {
  JSDOM = null;
}

const { extractOrdersFromDocument, extractOrderId } = require("../content.js");

function docFrom(fixture) {
  const html = fs.readFileSync(path.join(__dirname, "fixtures", fixture), "utf8");
  return new JSDOM(html).window.document;
}

test("extracts US orders (amazon.com)", { skip: !JSDOM && "jsdom not installed" }, () => {
  const orders = extractOrdersFromDocument(docFrom("orders_us.html"), { host: "amazon.com" });
  assert.equal(orders.length, 2);

  const o1 = orders.find((o) => o.orderId === "111-2222222-3333333");
  assert.ok(o1, "order 1 found by id");
  assert.equal(o1.orderDate, "2024-01-10");
  assert.equal(o1.orderTotalCents, 4376);
  assert.equal(o1.currency, "USD");
  assert.deepEqual(o1.items.map((i) => i.name).sort(),
    ["Crest ProHealth Advanced Mouthwash Mint 16 oz",
     "Glad Tall Kitchen Trash Bags OdorShield 13 Gallon"]);
  assert.equal(o1.items.find((i) => i.asin === "B00ABCDEFG").quantity, 1);

  const o2 = orders.find((o) => o.orderId === "114-5555555-6666666");
  assert.equal(o2.orderTotalCents, 1250);
  assert.equal(o2.items[0].quantity, 2); // "Qty: 2"
});

test("extracts UK orders with £ and DD Month YYYY (amazon.co.uk)",
  { skip: !JSDOM && "jsdom not installed" }, () => {
    const orders = extractOrdersFromDocument(docFrom("orders_uk.html"), { host: "amazon.co.uk" });
    assert.equal(orders.length, 1);
    const o = orders[0];
    assert.equal(o.orderId, "203-1234567-7654321");
    assert.equal(o.orderDate, "2024-01-12");
    assert.equal(o.orderTotalCents, 2999);
    assert.equal(o.currency, "GBP");
    assert.equal(o.items[0].asin, "B00UKKET01");
  });

test("currency falls back to host when not provided",
  { skip: !JSDOM && "jsdom not installed" }, () => {
    const orders = extractOrdersFromDocument(docFrom("orders_uk.html"), { host: "amazon.com.au" });
    assert.equal(orders[0].currency, "AUD");
  });

test("diagnostics mode returns {orders, report} with coverage",
  { skip: !JSDOM && "jsdom not installed" }, () => {
    const res = extractOrdersFromDocument(docFrom("orders_us.html"),
      { host: "amazon.com", diagnostics: true, path: "/your-orders/orders" });
    assert.ok(Array.isArray(res.orders));
    assert.equal(res.report.kind, "page");
    assert.equal(res.report.pathKind, "your-orders");
    assert.equal(res.report.cardSelectorUsed, ".order-card.js-order-card");
    assert.equal(res.report.coverage.cards, 2);
    assert.equal(res.report.coverage.orderTotal, 2);
    assert.equal(res.report.fieldFailures.length, 0);
    // No personal data on the report.
    const blob = JSON.stringify(res.report);
    assert.ok(!/Trash Bags|Mouthwash|111-2222222/.test(blob));
  });

test("diagnostics records redacted failures for a broken card",
  { skip: !JSDOM && "jsdom not installed" }, () => {
    const res = extractOrdersFromDocument(docFrom("orders_broken.html"),
      { host: "amazon.co.uk", diagnostics: true, path: "/your-orders/orders" });
    const report = res.report;
    assert.equal(report.coverage.cards, 2);
    // The broken card should have at least one failure entry.
    assert.ok(report.fieldFailures.length >= 1);
    const f = report.fieldFailures[0];
    assert.ok(f.missing.length >= 1);
    // Structural class hints captured to help fix selectors...
    assert.ok(f.classes.some((c) => /order-total-mystery|product-thumb/.test(c)));
    // ...but the real amount "99.95" must never appear; only its shape may.
    const blob = JSON.stringify(report);
    assert.ok(!/99\.95/.test(blob), "raw amount must not leak");
  });

test("extractOrderId matches physical and digital order ids",
  { skip: !JSDOM && "jsdom not installed" }, () => {
    function card(html) {
      return new JSDOM("<div class='order-card'>" + html + "</div>").window.document
        .querySelector(".order-card");
    }
    // Physical (3-7-7)
    assert.equal(extractOrderId(card("<span>701-7822882-8615449</span>")),
      "701-7822882-8615449");
    // Digital, letter-prefixed (e.g. Kindle/Alexa/app store)
    assert.equal(extractOrderId(card("<span>Order # D01-1234567-1234567</span>")),
      "D01-1234567-1234567");
    // From an href fallback with a letter-prefixed id
    assert.equal(
      extractOrderId(card('<a href="/order-details?orderID=D01-7654321-7654321">x</a>')),
      "D01-7654321-7654321");
  });

test("empty unrendered shells are not counted as coverage failures",
  { skip: !JSDOM && "jsdom not installed" }, () => {
    // Two empty order-card shells (client-side not rendered) + nothing else.
    const doc = new JSDOM(`<div class="your-orders-content">
      <div class="order-card js-order-card"></div>
      <div class="order-card js-order-card"></div>
    </div>`).window.document;
    const res = extractOrdersFromDocument(doc, { host: "amazon.ca", diagnostics: true });
    assert.equal(res.orders.length, 0);
    assert.equal(res.report.coverage.cards, 0);      // no *rendered* cards
    assert.equal(res.report.coverage.emptyShells, 2); // tracked separately
    assert.equal(res.report.fieldFailures.length, 0); // not counted as failures
  });

test("recovers order total from header when no explicit Total label",
  { skip: !JSDOM && "jsdom not installed" }, () => {
    const doc = new JSDOM(`<div class="your-orders-content">
      <div class="order-card js-order-card">
        <div class="order-header"><div class="a-fixed-right-grid">
          <span class="a-color-secondary">Order placed</span>
          <span class="value">January 5, 2025</span>
          <span class="value">CDN$ 34.23</span>
          <span class="value">702-1111111-2222222</span>
        </div></div>
        <a class="a-link-normal" href="/dp/B08BMV5VDL">Sunscreen</a>
      </div></div>`).window.document;
    const o = extractOrdersFromDocument(doc, { host: "amazon.ca" })[0];
    assert.equal(o.orderTotalCents, 3423);
    assert.equal(o.currency, "CAD");
  });

test("cancelled orders are skipped (never charged)",
  { skip: !JSDOM && "jsdom not installed" }, () => {
    const doc = new JSDOM(`<div class="your-orders-content">
      <div class="order-card js-order-card">
        <div class="order-header"><div class="a-fixed-right-grid">
          <span class="a-color-secondary">Order placed</span><span class="value">December 6, 2025</span>
          <span class="value">702-0045705-1427416</span>
        </div></div>
        <div class="a-size-base-plus a-text-bold">Cancelled</div>
        <div>Your order was cancelled. You have not been charged for this order.</div>
        <a class="a-link-normal" href="/dp/B00EXTCORD">Amazon Basics 15-Foot Extension Cord</a>
      </div>
      <div class="order-card js-order-card">
        <div class="order-header"><div class="a-fixed-right-grid">
          <span class="a-color-secondary">Order placed</span><span class="value">December 7, 2025</span>
          <span class="a-color-secondary">Total</span><span class="value">$19.99</span>
          <span class="value">702-1111111-2222222</span>
        </div></div>
        <a class="a-link-normal" href="/dp/B00REALITEM">A real shipped item</a>
      </div>
    </div>`).window.document;
    const res = extractOrdersFromDocument(doc, { host: "amazon.ca", diagnostics: true });
    // Only the non-cancelled order is kept.
    assert.equal(res.orders.length, 1);
    assert.equal(res.orders[0].orderId, "702-1111111-2222222");
    // The cancelled card is counted separately, not as a coverage failure.
    assert.equal(res.report.coverage.cancelled, 1);
    assert.equal(res.report.coverage.cards, 1);
    assert.equal(res.report.fieldFailures.length, 0);
  });

test("isCancelledCard detects the not-charged notice and status word",
  { skip: !JSDOM && "jsdom not installed" }, () => {
    const C = require("../content.js");
    function card(html) {
      return new JSDOM("<div class='order-card'>" + html + "</div>").window.document
        .querySelector(".order-card");
    }
    assert.equal(C.isCancelledCard(card("<div>You have not been charged for this order.</div>")), true);
    assert.equal(C.isCancelledCard(card("<h3>Cancelled</h3>")), true);
    assert.equal(C.isCancelledCard(card("<div>Delivered Dec 6</div><span>$19.99</span>")), false);
  });

test("extractOrderId tolerates an id glued to an adjacent value",
  { skip: !JSDOM && "jsdom not installed" }, () => {
    function card(html) {
      return new JSDOM("<div class='order-card'>" + html + "</div>").window.document
        .querySelector(".order-card");
    }
    // No whitespace between the total and the order id.
    assert.equal(extractOrderId(card("<span>$24.99</span><span>702-1234567-1234567</span>")),
      "702-1234567-1234567");
    // Dedicated element is read even if card text is messy.
    assert.equal(
      extractOrderId(card('<span>$5</span><span class="yohtmlc-order-id">Order # 113-9999999-8888888</span>')),
      "113-9999999-8888888");
  });
