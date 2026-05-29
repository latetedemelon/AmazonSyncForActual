"use strict";
const test = require("node:test");
const assert = require("node:assert");
const D = require("../lib/diagnostics.js");

test("shapeOf masks digits/letters but keeps structure", () => {
  assert.equal(D.shapeOf("$1,234.56"), "$#,###.##");
  assert.equal(D.shapeOf("£29.99"), "£##.##");
  assert.equal(D.shapeOf("19,99 €"), "##,## €");
  assert.equal(D.shapeOf("January 10, 2024"), "Xxxxxxx ##, ####");
  assert.equal(D.shapeOf("USD"), "XXX");
  assert.equal(D.shapeOf(""), "");
});

test("shapeOf never leaks the actual value", () => {
  const shape = D.shapeOf("Glad Tall Kitchen Trash Bags");
  assert.ok(!/Glad|Kitchen|Trash/.test(shape));
  assert.equal(shape, "Xxxx Xxxx Xxxxxxx Xxxxx Xxxx");
});

test("redactText scrubs urls, order ids and long numbers", () => {
  assert.equal(D.redactText("see https://amazon.com/x?y=1"), "see <url>");
  assert.equal(D.redactText("order 111-2222222-3333333 failed"),
    "order <orderid> failed");
  assert.equal(D.redactText("code 401234"), "code ######");
});

test("pathKind classifies pages without reading query strings", () => {
  assert.equal(D.pathKind("/your-orders/orders"), "your-orders");
  assert.equal(D.pathKind("/gp/css/order-history"), "order-history");
  assert.equal(D.pathKind("/gp/css/summary/print.html"), "invoice");
  assert.equal(D.pathKind("/gp/your-account/order-details"), "order-details");
  assert.equal(D.pathKind("/something-else"), "other");
});

test("ringPush keeps only the most recent N", () => {
  let arr = [];
  for (let i = 0; i < 5; i++) arr = D.ringPush(arr, i, 3);
  assert.deepEqual(arr, [2, 3, 4]);
});

test("summarizeReports aggregates coverage and failure patterns", () => {
  const reports = [
    {
      kind: "page", host: "amazon.com", pathKind: "your-orders",
      cardSelectorUsed: ".order-card.js-order-card", ordersExtracted: 2,
      coverage: { cards: 2, orderId: 2, orderDate: 2, orderTotal: 2, items: 2 },
      fieldFailures: []
    },
    {
      kind: "page", host: "amazon.co.uk", pathKind: "your-orders",
      cardSelectorUsed: ".order-card", ordersExtracted: 1,
      coverage: { cards: 2, orderId: 2, orderDate: 1, orderTotal: 1, items: 2 },
      fieldFailures: [
        { missing: ["orderTotal", "orderDate"], totalShape: "", dateShape: "",
          classes: ["order-total", "a-column"] }
      ]
    },
    { kind: "error", host: "amazon.com", pathKind: "your-orders",
      error: { name: "TypeError", message: "x is null" } }
  ];
  const s = D.summarizeReports(reports);
  assert.equal(s.pages, 2);
  assert.equal(s.errors, 1);
  assert.equal(s.health.cards, 4);
  assert.equal(s.health.orders, 3);
  // 3 dates recovered out of 4 cards => 0.75
  assert.equal(s.health.coverageRate.orderDate, 0.75);
  assert.equal(s.byContext.length, 2);
  assert.equal(s.failurePatterns[0].count, 1);
  assert.ok(s.failurePatterns[0].missing.includes("orderTotal"));
  assert.equal(s.errorCounts[0].count, 1);
});

test("summarizeReports handles empty input", () => {
  const s = D.summarizeReports([]);
  assert.equal(s.pages, 0);
  assert.equal(s.health.orderExtractionRate, null);
  assert.deepEqual(s.byContext, []);
});
