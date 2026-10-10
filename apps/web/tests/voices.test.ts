import assert from "node:assert/strict";
import test from "node:test";
import { voiceNames } from "@/lib/present";
import type { Span } from "@/lib/types";
import { registerTargets, topSlices, unknownVoices } from "@/lib/voices";

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
