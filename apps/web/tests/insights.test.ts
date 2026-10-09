import assert from "node:assert/strict";
import test from "node:test";
import { absenceNote, buildInsights, confirmationCounts, speechPerMinute, topicCounts } from "@/lib/insights";
import { emptyGraph } from "@/lib/graph";
import type { Claim, Finding, Span } from "@/lib/types";

function span(id: string, start: number, end: number, extra: Partial<Span> = {}): Span {
  return { id, kind: "speech", start_ms: start, end_ms: end, raw_text: id, text: id, coarse: false, overlap: false, session_id: null, seam: false, speaker_hypothesis_id: null, speaker_label: null, ...extra };
}

function claim(id: string, text: string, status: string, startMs: number | null = null): Claim {
  return {
    id, kind: "decision", decision_status: null, origin: "model", status, coarse: false, overlap: false, text, span_ids: [], confidence: status === "supported" ? "confirmed" : "unverified",
    citations: startMs === null ? [] : [{ span_id: "s1", quote: text, relation: "entails", char_start: 0, char_end: 1, start_ms: startMs, end_ms: startMs + 1, playback: "" }],
  };
}

function finding(id: string, dimension: Finding["dimension"], claimIds: string[]): Finding {
  return { id, dimension, stance: "supports", claim_ids: claimIds, text: id, none_in_transcript: false };
}

test("confirmation counts distinct statements and keeps the worst status", () => {
  const counts = confirmationCounts([
    claim("a", "The pilot starts Monday", "supported"),
    claim("b", "the pilot starts monday.", "unresolved"),
    claim("c", "Budget is due Friday", "supported"),
    claim("d", "Budget is due Friday", "supported"),
  ]);
  assert.deepEqual(counts, { confirmed: 1, unconfirmed: 1, contradicted: 0, numbers: 0, total: 2 });
});

test("topic counts separate present from absent topics", () => {
  const { present, absent } = topicCounts([finding("f1", "risk", ["a"]), finding("f2", "risk", ["a"]), finding("f3", "decision", ["a"])]);
  assert.deepEqual(present.map((row) => [row.dimension, row.count]), [["risk", 2], ["decision", 1]]);
  assert.ok(absent.includes("question") && !absent.includes("risk"));
});

test("speech per minute never exceeds sixty seconds even when spans overlap", () => {
  const rows = speechPerMinute([span("a", 0, 50_000), span("b", 10_000, 60_000), span("c", 90_000, 100_000)]);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].seconds, 60);
  assert.equal(rows[1].seconds, 10);
});

test("no charts are invented from an empty meeting", () => {
  assert.deepEqual(buildInsights(emptyGraph()), []);
});

test("a flat activity strip is not drawn, a varied one is", () => {
  const flat = { ...emptyGraph(), spans: Array.from({ length: 6 }, (_, n) => span(`s${n}`, n * 60_000, n * 60_000 + 58_000)) };
  assert.equal(buildInsights(flat).some((item) => item.id === "activity"), false);
  const varied = { ...emptyGraph(), spans: [span("s0", 0, 55_000), span("s1", 60_000, 70_000), span("s2", 120_000, 170_000), span("s3", 180_000, 185_000)] };
  assert.equal(buildInsights(varied).some((item) => item.id === "activity"), true);
});

test("a single unassigned speaker does not produce a speaker chart", () => {
  const graph = { ...emptyGraph(), speakers: [{ id: "unassigned", label: null, duration_ms: 1_000_000, duration_share: 1, turn_count: 1 }] };
  assert.equal(buildInsights(graph).some((item) => item.id === "speakers"), false);
});

test("key-moment points come only from findings whose claims carry a timed citation", () => {
  const graph = {
    ...emptyGraph(),
    spans: [span("s1", 0, 10_000)],
    claims: [claim("c1", "x", "supported", 5_000), claim("c2", "y", "supported", null)],
    findings: [finding("f1", "decision", ["c1"]), finding("f2", "risk", ["c2"])],
  };
  const moments = buildInsights(graph).find((item) => item.kind === "moments");
  assert.ok(moments && moments.kind === "moments");
  assert.deepEqual(moments.lanes.map((lane) => lane.key), ["decision"]);
});

test("silence, picture notes and untranscribed windows are not speech", () => {
  const rows = speechPerMinute([
    span("a", 0, 30_000),
    span("quiet", 30_000, 150_000, { kind: "silence", text: "", raw_text: "" }),
    span("lost", 150_000, 240_000, { kind: "untranscribed", text: "", raw_text: "" }),
    span("blank", 240_000, 300_000, { text: "  ", raw_text: "" }),
  ]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].seconds, 30);
});

test("'Not mentioned' is only claimed when nothing is unconfirmed or missing", () => {
  const graph = emptyGraph();
  assert.match(absenceNote(["risk"], graph) ?? "", /^Not mentioned: Risks/);
  assert.match(absenceNote(["risk"], graph, 3) ?? "", /^No confirmed points on: Risks/);
  const lost = { ...graph, spans: [span("x", 0, 1000, { kind: "untranscribed", text: "", raw_text: "" })] };
  assert.match(absenceNote(["risk"], lost) ?? "", /^No confirmed points on/);
  const unevaluated = { ...graph, not_evaluated: ["risk" as const] };
  assert.equal(absenceNote(["risk"], unevaluated), "Not analysed: Risks.");
});
