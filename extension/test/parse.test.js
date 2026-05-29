"use strict";
const test = require("node:test");
const assert = require("node:assert");
const A = require("../lib/parse.js");

test("parseMoneyToCents across English marketplaces", () => {
  assert.equal(A.parseMoneyToCents("$43.76"), 4376);        // US / AU / SG / CA $
  assert.equal(A.parseMoneyToCents("£29.99"), 2999);        // UK
  assert.equal(A.parseMoneyToCents("A$12.34"), 1234);       // Australia
  assert.equal(A.parseMoneyToCents("S$9.50"), 950);         // Singapore
  assert.equal(A.parseMoneyToCents("₹1,23,456.78"), 12345678); // India (lakh grouping)
  assert.equal(A.parseMoneyToCents("R 199.00"), 19900);     // South Africa
  assert.equal(A.parseMoneyToCents("AED 100.00"), 10000);   // UAE
  assert.equal(A.parseMoneyToCents("19,99 €"), 1999);       // euro comma-decimal
  assert.equal(A.parseMoneyToCents("(5,00 $)"), -500);      // parenthesised credit
  assert.equal(A.parseMoneyToCents(""), null);
});

test("currencyForHost maps marketplaces", () => {
  assert.equal(A.currencyForHost("www.amazon.com"), "USD");
  assert.equal(A.currencyForHost("www.amazon.ca"), "CAD");
  assert.equal(A.currencyForHost("www.amazon.co.uk"), "GBP");
  assert.equal(A.currencyForHost("www.amazon.com.au"), "AUD");
  assert.equal(A.currencyForHost("www.amazon.in"), "INR");
  assert.equal(A.currencyForHost("www.amazon.sg"), "SGD");
  assert.equal(A.currencyForHost("www.amazon.ie"), "EUR");
  assert.equal(A.currencyForHost("www.amazon.ae"), "AED");
  assert.equal(A.currencyForHost("www.amazon.co.za"), "ZAR");
  assert.equal(A.currencyForHost("smile.amazon.co.uk"), "GBP"); // subdomain
  assert.equal(A.currencyForHost("unknown.example"), "USD");    // fallback
});

test("normalizeDate handles US and UK styles", () => {
  assert.equal(A.normalizeDate("January 10, 2024"), "2024-01-10");
  assert.equal(A.normalizeDate("12 January 2024"), "2024-01-12");
  assert.equal(A.normalizeDate("2024-01-10T08:00:00Z"), "2024-01-10");
  assert.equal(A.normalizeDate("not a date"), "not a date");
});

test("centsToAmountString and parseQuantity", () => {
  assert.equal(A.centsToAmountString(4376), "43.76");
  assert.equal(A.centsToAmountString(5), "0.05");
  assert.equal(A.parseQuantity("Qty: 3"), 3);
  assert.equal(A.parseQuantity(""), 1);
});

test("ordersToCsv emits importer-compatible headers", () => {
  const csv = A.ordersToCsv([
    {
      orderId: "111-2222222-3333333", orderDate: "2024-01-10",
      orderTotalCents: 4376, currency: "USD",
      items: [
        { name: "Trash Bags", quantity: 1, asin: "B00ABCDEFG" },
        { name: "Mouthwash, 16oz", quantity: 2, asin: "B00HIJKLMN" }
      ]
    }
  ]);
  const lines = csv.trim().split("\n");
  assert.equal(lines[0],
    "Order ID,Order Date,Ship Date,Product Name,Quantity,Unit Price,Total Owed,Order Total,ASIN,Currency");
  // Quotes a field containing a comma.
  assert.ok(lines[2].includes('"Mouthwash, 16oz"'));
  // Order total repeated on each row (importer dedups via override).
  assert.ok(lines[1].endsWith("43.76,B00ABCDEFG,USD"));
});

test("mergeOrders de-duplicates by order id and items", () => {
  const a = [{ orderId: "X", orderDate: "2024-01-01", orderTotalCents: 100, currency: "USD",
               items: [{ name: "A", asin: "AAA" }] }];
  const b = [{ orderId: "X", orderDate: "", orderTotalCents: null, currency: "USD",
               items: [{ name: "A", asin: "AAA" }, { name: "B", asin: "BBB" }] }];
  const merged = A.mergeOrders(a, b);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].items.length, 2);
  assert.equal(merged[0].orderTotalCents, 100);
});
