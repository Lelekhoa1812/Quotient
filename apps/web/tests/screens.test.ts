import assert from "node:assert/strict";
import test from "node:test";
import { buildScreenCards } from "@/lib/screens";
import type { ScreenView } from "@/lib/types";

const screen = (id: string, start: number, end: number, title: string, text: string, kind = "ui"): ScreenView => ({ id, kind, title, text, details: "A browser window.", start_ms: start, end_ms: end });
const NAV = "Home\nSales\nPurchasing\nInventory\nProduction\nDispatch\nAccounting\nReports\nAdmin";
const dashboard = [
  "Today's Trading Snapshot | FoodF[unreadable]", "FoodFlow", "https://staging.foodflow.com.au/dashboard", "TEST STAGING", NAV,
  "Dashboard", "Sales, purchasing, inventory, and freshness at a glance", "Sales This Week", "Demo sample", "$184,750", "Live recent orders unavailable or empty",
  "Purchases This Week", "Demo sample", "$96,320", "Inventory Value", "Demo sample", "$312,480", "13 at-risk SKUs need attention",
].join("\n");
const rows = (n: number) => Array.from({ length: n }, (_, i) => `SO-0${1231 + i}\nRetail Customer (C0001)\nNew\nMetro\nRun 02\nTue, 06 Oct\n$${100 + i}.00`).join("\n");

test("a screen is read as a plain title and copied highlights, with the frame, tab title, url and unreadable parts gone", () => {
  const frame = (id: string, start: number) => screen(id, start, start + 8000, "", `Some | Tab\nFoodFlow\nTEST STAGING\n${NAV}\nOther ${id}\nbody line for ${id}`);
  const [card] = buildScreenCards([screen("a", 296000, 304000, "Today's Trading Snapshot", dashboard), frame("b", 304000), frame("c", 312000), frame("d", 320000)]);
  assert.equal(card.title, "Today's Trading Snapshot");
  assert.deepEqual(card.highlights.map((item) => [item.label, item.value, item.sample]), [
    ["Sales This Week", "$184,750", true], ["Purchases This Week", "$96,320", true], ["Inventory Value", "$312,480", true],
  ]);
  const text = card.lines.join("\n");
  for (const noise of ["[unreadable]", "https://", "TEST STAGING", "Purchasing\nInventory", " | "]) assert.ok(!text.includes(noise), noise);
  assert.ok(text.includes("Live recent orders unavailable or empty"));
});

test("an email, the line that labels it, and a table body never reach the card", () => {
  const signIn = screen("a", 0, 5000, "Sign in", "Welcome back\nLast used\ndemo-jan@yopmail.com\nPassword\nContinue", "screen_share");
  assert.ok(!buildScreenCards([signIn])[0].lines.join(" ").match(/yopmail|Last used|Continue/));
  const list = buildScreenCards([screen("b", 0, 5000, "Sales orders", `Sales orders\nCustomer\nNew\n${rows(12)}`)])[0];
  assert.equal(list.moreRows, 10);
  assert.ok(list.lines.join("\n").includes("SO-01231") && !list.lines.join("\n").includes("SO-01240"));
  assert.deepEqual(list.highlights, []); // a table's price and date cells are not headline figures
});

test("a record's totals are kept after its rows, and a figure shown as a demo sample says so", () => {
  const record = screen("a", 0, 9000, "#SO-01299", `Order\n${rows(5)}\nTotal cost ex Tax\n$329.52\nTotal sales ex Tax\n$411.90\nNet profit ex Tax\n$0.00\nMargin\n0%`);
  const labels = buildScreenCards([record])[0].highlights.map((item) => `${item.label}=${item.value}`);
  assert.deepEqual(labels, ["Total cost ex Tax=$329.52", "Total sales ex Tax=$411.90", "Net profit ex Tax=$0.00", "Margin=0%"]);
});

test("readings of one page become one card, and a screen with nothing readable is folded", () => {
  const cards = buildScreenCards([
    screen("a", 0, 30000, "Sales orders", "Sales orders\nNeeds approval filter bar here\nA line about orders"),
    screen("b", 30000, 60000, "Sales orders", "Sales orders\nNeeds approval filter bar here\nA line about orders\nAnother line"),
    screen("c", 60000, 68000, "Chat", "Today's Trading Snapshot | [unreadable]\nLoading...\nChat", "screen_share"),
  ]);
  assert.equal(cards.length, 2);
  assert.deepEqual([cards[0].ids, cards[0].startMs, cards[0].endMs], [["a", "b"], 0, 60000]);
  assert.equal(cards[0].lines.length, 3); // the fuller reading wins
  assert.equal(cards[1].folded, true);
});

test("a breadcrumb, a date or a number-led label is not a headline figure", () => {
  const card = buildScreenCards([screen("a", 0, 9000, "Roles", "Admin > Roles\n142\nDate\n06/10/2026\n13 lots need attention\nFresh 68% · 68")])[0];
  assert.deepEqual(card.highlights, []);
});
