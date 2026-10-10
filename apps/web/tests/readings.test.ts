import assert from "node:assert/strict";
import test from "node:test";
import { parseDigest } from "@/lib/digest";
import { attachReadings } from "@/lib/readings";
import type { ScreenCard } from "@/lib/screens";

const card = (id: string, startMs: number, ids = [id]): ScreenCard => ({
  id, ids, kind: "ui", title: id, startMs, endMs: startMs + 8000, highlights: [], lines: ["a", "b"], moreRows: 0, folded: false, raw: "", layout: "",
});

test("a reading joins the card it belongs to, and a talk-backed one is preferred", () => {
  const cards = attachReadings(
    [card("a", 0, ["a", "b"]), card("c", 20_000)],
    [
      { id: "b", reading: "From the screen alone.", differs: null, spanIds: [], startMs: 0 },
      { id: "a", reading: "The presenter opens the dashboard to show the week's sales.", differs: "The screen shows a login and a speaker said it should be public.", spanIds: ["s1"], startMs: 0 },
    ],
  );
  assert.equal(cards[0].reading, "The presenter opens the dashboard to show the week's sales.");
  assert.match(cards[0].differs ?? "", /public/);
  assert.equal(cards[1].reading, undefined);
});

test("a digest without readings parses as an empty list, and a blank reading is dropped", () => {
  const digest = parseDigest({
    screen_uses: [
      { id: "sc", reading: "The roles page is where a custom role is copied.", span_ids: ["s1"], start_ms: 1000 },
      { id: "nope", reading: "  " },
    ],
  });
  assert.deepEqual(digest?.screenUses.map((use) => use.id), ["sc"]);
});
