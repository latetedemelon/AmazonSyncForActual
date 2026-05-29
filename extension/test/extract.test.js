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

const { extractOrdersFromDocument } = require("../content.js");

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
