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

test("normalizeDate rejects implausible (epoch/garbage) dates", () => {
  // The "Alexa+" subscription card produced these; never emit a 1970 date.
  assert.equal(A.normalizeDate("January 1, 1970"), "");
  assert.equal(A.normalizeDate("Thu Jan 01 1970"), "");
  assert.equal(A.normalizeDate("1970-01-01"), "");
  assert.equal(A.normalizeDate("1999-12-31"), "");        // before Amazon-era floor
  assert.equal(A.normalizeDate("2099-01-01"), "");        // far future
  assert.equal(A.normalizeDate("January 10, 2024"), "2024-01-10"); // still works
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

test("buildBridgeOptions includes only set values", () => {
  assert.deepEqual(A.buildBridgeOptions({ noteMode: "fill", account: "", days: "" }),
    { note_mode: "fill" });
  assert.deepEqual(
    A.buildBridgeOptions({ noteMode: "prepend", account: "Amazon Card", days: "30" }),
    { note_mode: "prepend", account: "Amazon Card", days: 30 });
  assert.deepEqual(A.buildBridgeOptions({}), {});
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

// ---- pagination / time-filter helpers (need a DOM) ----
let JSDOM2 = null;
try { ({ JSDOM: JSDOM2 } = require("jsdom")); } catch (e) { JSDOM2 = null; }
function dom(html) { return new JSDOM2(html).window.document; }

test("nextStartIndex follows a real Next link", { skip: !JSDOM2 && "no jsdom" }, () => {
  const doc = dom(`<ul class="a-pagination">
    <li class="a-normal"><a href="?startIndex=0">1</a></li>
    <li class="a-selected"><a>2</a></li>
    <li class="a-last"><a href="/your-orders?startIndex=20&x=1">Next</a></li>
  </ul>`);
  assert.equal(A.nextStartIndex(doc, 10, 10), 20);
});

test("nextStartIndex returns null on the last page", { skip: !JSDOM2 && "no jsdom" }, () => {
  const doc = dom(`<ul class="a-pagination">
    <li class="a-normal"><a href="?startIndex=10">prev</a></li>
    <li class="a-last a-disabled"><span>Next</span></li>
  </ul>`);
  assert.equal(A.nextStartIndex(doc, 20, 10), null);
});

test("nextStartIndex guesses next page only when the page is full",
  { skip: !JSDOM2 && "no jsdom" }, () => {
    // Full page (10 cards), no pagination markup -> guess current+pageSize.
    var full = "<div>no pagination</div>" +
      new Array(10).fill('<div class="order-card js-order-card">x</div>').join("");
    assert.equal(A.nextStartIndex(dom(full), 30, 10), 40);
  });

test("nextStartIndex returns null on a short/empty last page (no infinite paging)",
  { skip: !JSDOM2 && "no jsdom" }, () => {
    // 3 cards on a page of 10, no pagination -> this is the last page.
    var short = new Array(3).fill('<div class="order-card js-order-card">x</div>').join("");
    assert.equal(A.nextStartIndex(dom(short), 0, 10), null);
    // Completely empty (old/empty year) -> null, so the walk stops.
    assert.equal(A.nextStartIndex(dom("<div>You have no orders in 2013.</div>"), 0, 10), null);
  });

test("findTimeFilters reads window+year+archived options, years newest-first",
  { skip: !JSDOM2 && "no jsdom" }, () => {
    const doc = dom(`<select name="timeFilter">
      <option value="months-3">Last 3 months</option>
      <option value="year-2025">2025</option>
      <option value="year-2026">2026</option>
      <option value="archived">Archived Orders</option>
      <option value="months-3">dupe</option>
      <option value="not-a-period">junk</option>
    </select>`);
    const values = A.findTimeFilters(doc).map((f) => f.value);
    // dupe + junk dropped; windows/archived before years; years newest-first.
    assert.deepEqual(values, ["months-3", "archived", "year-2026", "year-2025"]);
  });

test("findTimeFilters also reads custom dropdown links",
  { skip: !JSDOM2 && "no jsdom" }, () => {
    const doc = dom(`<ul>
      <li><a href="/your-orders/orders?timeFilter=year-2024&startIndex=0">2024</a></li>
      <li><a href="/your-orders/orders?timeFilter=year-2023">2023</a></li>
    </ul>`);
    const values = A.findTimeFilters(doc).map((f) => f.value);
    assert.deepEqual(values, ["year-2024", "year-2023"]);
  });

test("applyTimeFilter sets both params and resets startIndex",
  { skip: !JSDOM2 && "no jsdom" }, () => {
    const out = A.applyTimeFilter(
      "https://www.amazon.ca/your-orders/orders?timeFilter=year-2026&startIndex=30", "year-2024");
    assert.ok(out.includes("timeFilter=year-2024"));
    assert.ok(out.includes("orderFilter=year-2024"));
    assert.ok(out.includes("startIndex=0"));
  });

test("summarizeOrdersByYear buckets by year, newest first, with totals", () => {
  const orders = [
    { orderDate: "2025-03-01", orderTotalCents: 1000, items: [{}, {}] },
    { orderDate: "2025-11-15", orderTotalCents: 2500, items: [{}] },
    { orderDate: "2024-06-01", orderTotalCents: 500, items: [{}] },
    { orderDate: "", orderTotalCents: null, items: [] },          // unknown date
    { orderDate: "2024-01-10T08:00:00Z", orderTotalCents: 700, items: [{}] },
  ];
  const s = A.summarizeOrdersByYear(orders);
  assert.deepEqual(s.rows.map((r) => r.year), ["2025", "2024", "unknown"]);
  const y2025 = s.rows.find((r) => r.year === "2025");
  assert.equal(y2025.orders, 2);
  assert.equal(y2025.items, 3);
  assert.equal(y2025.totalCents, 3500);
  assert.equal(s.totals.orders, 5);
  assert.equal(s.totals.totalCents, 4700);
});

test("summarizeOrdersByYear handles empty input", () => {
  const s = A.summarizeOrdersByYear([]);
  assert.deepEqual(s.rows, []);
  assert.equal(s.totals.orders, 0);
});

test("fullHistoryFilters drops rolling windows, keeps years + archived", () => {
  const filters = [
    { label: "Last 3 months", value: "months-3" },
    { label: "Last 30 days", value: "last30" },
    { label: "2026", value: "year-2026" },
    { label: "2025", value: "year-2025" },
    { label: "Archived Orders", value: "archived" },
  ];
  const kept = A.fullHistoryFilters(filters).map((f) => f.value);
  assert.deepEqual(kept, ["year-2026", "year-2025", "archived"]);
});

test("fullHistoryFilters falls back to all when no year buckets exist", () => {
  const filters = [{ label: "Last 3 months", value: "months-3" }];
  assert.deepEqual(A.fullHistoryFilters(filters).map((f) => f.value), ["months-3"]);
  assert.deepEqual(A.fullHistoryFilters([]), []);
});
