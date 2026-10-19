import assert from "node:assert/strict";
import test from "node:test";
import { voiceNames } from "@/lib/present";
import type { Span } from "@/lib/types";
import { registerTargets, talkTime, topSlices, unknownVoices } from "@/lib/voices";

let counter = 0;
function span(voice: string | null, startS: number, endS: number, text = "this is a reasonably long sentence about the plan for next week", extra: Partial<Span> = {}): Span {
  counter += 1;
  return {
    id: `s${counter}`,
    kind: "speech",
    start_ms: startS * 1000,
    end_ms: endS * 1000,
    raw_text: text,
    text,
    coarse: false,
    overlap: false,
    session_id: null,
    seam: false,
    speaker_hypothesis_id: voice,
    speaker_label: null,
    speaker_identity: null,
    ...extra,
  };
}

test("a typed name beats the analysis's name, which beats a name from the transcript", () => {
  const spans = [span("spk_0", 0, 5, "x", { speaker_label: "Typed" }), span("spk_1", 5, 9)];
  const names = voiceNames(spans, [{ id: "spk_1", name: "spoken", role: null }, { id: "spk_0", name: "spoken zero", role: null }], {
    spk_0: { name: "From Picture" },
    spk_1: { name: "jason lee" },
  });
  assert.equal(names.get("spk_0"), "Typed");
  assert.equal(names.get("spk_1"), "Jason Lee");
});

test("unknown voices are those no source named, most talkative first", () => {
  const spans = [span("spk_0", 0, 10), span("spk_1", 10, 14), span("spk_2", 14, 40), span(null, 40, 45)];
  const names = voiceNames(spans, [], { spk_0: { name: "Ana" } });
  assert.deepEqual(unknownVoices(spans, names), ["spk_2", "spk_1"]);
});

test("the top three slices are far apart and in time order", () => {
  const spans = [
    span("spk_3", 10, 18), span("spk_3", 20, 28), // one turn (gap under 1.5 s is not reached: 2 s), kept apart
    span("spk_3", 100, 112), span("spk_3", 300, 306),
    span("spk_3", 500, 503, "ok"), span("spk_1", 40, 60),
  ];
  const slices = topSlices(spans, "spk_3", 3);
  assert.equal(slices.length, 3);
  assert.deepEqual(slices.map((slice) => slice.startMs).sort((a, b) => a - b), slices.map((slice) => slice.startMs));
  for (const slice of slices) assert.ok(slice.endMs - slice.startMs <= 20_000);
  const starts = slices.map((slice) => slice.startMs);
  assert.ok(starts[1] - starts[0] >= 45_000 && starts[2] - starts[1] >= 45_000);
});

test("neighbouring lines of one voice become one turn, and another voice interrupts it", () => {
  const spans = [span("spk_3", 0, 2), span("spk_3", 2.5, 5), span("spk_1", 5.2, 7), span("spk_3", 7.5, 10)];
  const slices = topSlices(spans, "spk_3", 3);
  assert.equal(slices.length, 2);
  assert.ok(slices[0].text.split(" ").length > 12); // the first two lines joined
});

test("a voice that only ever interjects still gets its slices, and overlapped speech is last", () => {
  const spans = [span("spk_9", 5, 6, "yeah"), span("spk_9", 50, 51, "right", { overlap: true }), span("spk_9", 99, 100, "okay")];
  const slices = topSlices(spans, "spk_9", 3);
  assert.equal(slices.length, 3);
  assert.deepEqual(topSlices([], "spk_9"), []);
  assert.deepEqual(topSlices([span("spk_1", 0, 5)], "spk_9"), []);
});

test("clips never start before zero and never run past twenty seconds", () => {
  const long = span("spk_4", 0, 120, "word ".repeat(100));
  const [slice] = topSlices([long], "spk_4", 3);
  assert.equal(slice.startMs, 0);
  assert.equal(slice.endMs, 20_000);
});

test("register targets list each detected person once and never the voice itself", () => {
  const names = new Map([["spk_0", "Maddy"], ["spk_1", "Jason"], ["spk_2", "maddy"], ["spk_3", ""]]);
  assert.deepEqual(registerTargets(names, "spk_1").map((item) => item.name), ["Maddy"]);
});

test("talkTime groups split voice IDs with identical or alias names into a single bar", () => {
  const spans = [
    span("spk_5", 0, 32),   // 32 seconds
    span("spk_8", 32, 33),  // 1 second, split voice for Bill
    span("spk_3", 33, 49),  // 16 seconds
    span("spk_7", 49, 50),  // 1 second, split voice for Liam
  ];
  const names = new Map([
    ["spk_5", "Bill Kollatos"],
    ["spk_8", "Bill Kollatos"],
    ["spk_3", "Liam Le"],
    ["spk_7", "Liam Le"],
  ]);
  const rows = talkTime(spans, names);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].name, "Bill Kollatos");
  assert.equal(rows[0].id, "spk_5");
  assert.deepEqual(rows[0].voiceIds, ["spk_5", "spk_8"]);
  assert.equal(rows[0].share, 33 / 50);

  assert.equal(rows[1].name, "Liam Le");
  assert.equal(rows[1].id, "spk_3");
  assert.deepEqual(rows[1].voiceIds, ["spk_3", "spk_7"]);
  assert.equal(rows[1].share, 17 / 50);
});

test("talkTime keeps distinct anonymous speakers as separate bars", () => {
  const spans = [
    span("spk_0", 0, 10),
    span("spk_1", 10, 25),
  ];
  const names = new Map<string, string>();
  const rows = talkTime(spans, names);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].name, "Speaker 2");
  assert.equal(rows[0].id, "spk_1");
  assert.equal(rows[1].name, "Speaker 1");
  assert.equal(rows[1].id, "spk_0");
});

test("talkTime unifies real video kollab.mp4 meeting into exactly three canonical participants", () => {
  const spans: Span[] = [
    // Bill: 728 spans, total ~3290s
    span("spk_5", 0, 3290, "bill talks", { speaker_display: "Bill Kollatos" }),
    // Liam: 347 spans, total ~2260s
    span("spk_3", 3300, 5560, "liam talks", { speaker_display: "Liam Le" }),
    // Liam split: 1 span, 8s
    span("spk_7", 5560, 5568, "review as client", { speaker_display: "Liam Le" }),
    // Ly Ho: 169 spans, total ~970s
    span("spk_4", 5570, 6540, "ly talks", { speaker_display: "Ly Ho" }),
  ];
  const digestSpeakers = [
    { id: "spk_0", name: "Liam Le", role: null },
    { id: "spk_3", name: "Liam", role: null },
    { id: "spk_4", name: "Lee", role: null },
    { id: "spk_5", name: "Bill", role: null },
    { id: "spk_10", name: "Bill Kollatos", role: null },
  ];
  const identities = {
    spk_0: { name: "Liam Le" },
    spk_10: { name: "Bill Kollatos" },
    spk_3: { name: "Liam" },
    spk_4: { name: "Lee" },
    spk_5: { name: "Bill" },
  };

  const names = voiceNames(spans, digestSpeakers, identities);
  const rows = talkTime(spans, names);

  // Exactly 3 unified people
  assert.equal(rows.length, 3);

  // 1. Bill Kollatos (primary spk_5, ~50.4%)
  assert.equal(rows[0].name, "Bill Kollatos");
  assert.equal(rows[0].id, "spk_5");
  assert.ok(Math.abs(rows[0].share - 0.504) < 0.01);

  // 2. Liam Le (primary spk_3, unifies spk_3 + spk_7, ~34.7%)
  assert.equal(rows[1].name, "Liam Le");
  assert.equal(rows[1].id, "spk_3");
  assert.deepEqual(rows[1].voiceIds, ["spk_3", "spk_7"]);
  assert.ok(Math.abs(rows[1].share - 0.347) < 0.01);

  // 3. Ly Ho (primary spk_4, ~14.9%)
  assert.equal(rows[2].name, "Ly Ho");
  assert.equal(rows[2].id, "spk_4");
  assert.ok(Math.abs(rows[2].share - 0.149) < 0.01);
});

