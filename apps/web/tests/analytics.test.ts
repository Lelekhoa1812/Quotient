import assert from "node:assert/strict";
import test from "node:test";
import { unionMs, bucketWidth, buckets, cumulative, evidenceByTopic, evidenceMix, handoffs, momentLanes, topicMix, voiceStats, wordCount } from "@/lib/analytics";
import type { Digest } from "@/lib/digest";
import type { Claim, Span } from "@/lib/types";

function span(id: string, start: number, end: number, voice: string | null, text = "one two three four"): Span {
  return { id, kind: "speech", start_ms: start, end_ms: end, raw_text: text, text, coarse: false, overlap: false, session_id: null, seam: false, speaker_hypothesis_id: voice, speaker_label: null, speaker_identity: null };
}

function claim(id: string, text: string, confidence: Claim["confidence"], at: number | null, kind = "figure"): Claim {
  return {
    id, kind, decision_status: null, origin: "model", status: "supported", coarse: false, overlap: false, text, span_ids: [], confidence,
    citations: at === null ? [] : [{ span_id: "s", quote: text, relation: "entails", char_start: 0, char_end: 1, start_ms: at, end_ms: at + 1, playback: "" }],
  };
}

const NAMES = new Map([["spk_0", "Priya"]]);

test("voice stats: share, words, turns and pace come from speech only", () => {
  const spans = [span("a", 0, 6000, "spk_0"), span("b", 6000, 8000, "spk_1"), span("c", 9000, 15000, "spk_0"), { ...span("d", 0, 5000, "spk_1"), kind: "silence" }];
  const voices = voiceStats(spans, NAMES);
  assert.deepEqual(voices.map((voice) => [voice.id, voice.name]), [["spk_0", "Priya"], ["spk_1", "Speaker 2"]]);
  assert.equal(voices[0].ms, 12000);
  assert.equal(Math.round(voices[0].share * 100), 86);
  assert.equal(voices[0].turns, 2);
  assert.equal(voices[0].words, 8);
  assert.equal(voices[0].wpm, 40);
});

test("a span crossing a bucket edge is shared out by overlap, never duplicated", () => {
  const out = buckets([span("a", 50_000, 70_000, "spk_0", "w w w w w w w w w w")], 60_000, 120_000);
  assert.equal(out.length, 2);
  assert.equal(out[0].ms, 10_000);
  assert.equal(out[1].ms, 10_000);
  assert.equal(Math.round(out[0].words + out[1].words), 10);
  assert.equal(out[0].byVoice.spk_0, 10_000);
});

test("bucket width keeps the column count readable", () => {
  assert.equal(bucketWidth(10 * 60_000), 15_000);
  assert.equal(bucketWidth(15 * 60_000), 30_000);
  assert.equal(bucketWidth(25 * 60_000), 60_000);
  assert.equal(bucketWidth(84 * 60_000), 120_000);
});

test("topic mix splits each topic's time by voice", () => {
  const chapters = [{ title: "A", gist: "", startMs: 0, endMs: 10_000, startSpanId: "a" }, { title: "B", gist: "", startMs: 10_000, endMs: 20_000, startSpanId: "b" }];
  const mix = topicMix(chapters, [span("a", 0, 12_000, "spk_0"), span("b", 12_000, 20_000, "spk_1")]);
  assert.deepEqual(mix.map((row) => [row.title, row.byVoice.spk_0 ?? 0, row.byVoice.spk_1 ?? 0]), [["A", 10_000, 0], ["B", 2_000, 8_000]]);
});

test("hand-offs count changes of voice and ignore long silences", () => {
  const out = handoffs([span("a", 0, 5000, "spk_0"), span("b", 5000, 9000, "spk_1"), span("c", 9500, 12_000, "spk_0"), span("d", 60_000, 65_000, "spk_1")]);
  assert.deepEqual(out.map((row) => [row.from, row.to, row.count]), [["spk_0", "spk_1", 1], ["spk_1", "spk_0", 1]]);
});

test("evidence mix counts distinct statements at their weakest tier", () => {
  const claims = [claim("1", "Pilot starts Monday", "confirmed", 1000), claim("2", "pilot starts monday.", "unverified", 2000), claim("3", "Budget is 10k", "likely", 3000)];
  assert.deepEqual(evidenceMix(claims), { confirmed: 0, likely: 1, unchecked: 1, contradicted: 0 });
  const chapters = [{ title: "A", gist: "", startMs: 0, endMs: 2500, startSpanId: "a" }, { title: "B", gist: "", startMs: 2500, endMs: 9000, startSpanId: "b" }];
  const rows = evidenceByTopic(claims, chapters);
  assert.deepEqual(rows.map((row) => [row.counts.unchecked, row.counts.likely]), [[1, 0], [0, 1]]);
});

function digest(overrides: Partial<Digest>): Digest {
  return { contentType: "meeting", title: "", summary: [], outcome: null, speakers: [], perspectives: [], chapters: [], decisions: [], actions: [], questions: [], disagreements: [], figures: [], risks: [], concepts: [], diagram: null, screenUses: [], ...overrides };
}

test("moment lanes and running totals only include what exists", () => {
  const d = digest({
    questions: [
      { question: "Who?", askedBy: null, startMs: 1000, askedSpanId: "a", answered: true, answer: "Me", answerMs: 4000, answerSpanId: "b" },
      { question: "When?", askedBy: null, startMs: 2000, askedSpanId: "c", answered: false, answer: null, answerMs: null, answerSpanId: null },
    ],
    decisions: [{ statement: "Go", status: "agreed", by: null, spanIds: [], basis: "confirmed", startMs: 5000 }],
  });
  assert.deepEqual(momentLanes(d).map((lane) => lane.key), ["decisions", "questions"]);
  const totals = cumulative(d);
  assert.deepEqual(totals.map((series) => [series.key, series.steps.length]), [["questions", 2], ["answers", 1], ["decisions", 1]]);
  assert.deepEqual(totals[0].steps, [{ atMs: 1000, value: 1 }, { atMs: 2000, value: 2 }]);
});

test("word counting handles apostrophes and numbers", () => {
  assert.equal(wordCount("It's 1,000 orders — don't stop"), 6);
});

test("talk time counts overlapping voices once", () => {
  assert.equal(unionMs([span("a", 0, 10_000, "spk_0"), span("b", 5_000, 12_000, "spk_1"), span("c", 20_000, 21_000, "spk_0")]), 13_000);
});

test("overlapping lines of one voice are counted once in its talk time", () => {
  const voices = voiceStats([span("a", 0, 10_000, "spk_0"), span("b", 5_000, 12_000, "spk_0")], new Map());
  assert.equal(voices[0].ms, 12_000);
});

test("one corrupt span time cannot make the buckets crash or ask for an enormous array", () => {
  assert.deepEqual(buckets([span("a", 0, 1000, "spk_0", "hello")], 60_000, Number.POSITIVE_INFINITY), []);
  assert.deepEqual(buckets([span("a", 0, 1000, "spk_0", "hello")], 60_000, Number.NaN), []);
  assert.ok(buckets([span("a", 0, 1000, "spk_0", "hello")], 1, 1e30).length <= 1000);
  // A negative start is clipped to the first bucket instead of indexing before it.
  const out = buckets([span("a", -5000, 4000, "spk_0", "w w w w w w w w w")], 60_000, 120_000);
  assert.equal(out.length, 2);
  assert.ok(out[0].ms > 0 && out[0].ms <= 4000);
});
