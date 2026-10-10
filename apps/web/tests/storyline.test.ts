import assert from "node:assert/strict";
import test from "node:test";
import { BOUNDARY_SLACK_MS, buildStoryline, topicIndex } from "@/lib/storyline";
import type { Digest } from "@/lib/digest";
import type { ScreenCard } from "@/lib/screens";

const chapter = (title: string, startMs: number, endMs: number) => ({ title, gist: "", startMs, endMs, startSpanId: "s" });
const card = (id: string, startMs: number, folded = false, title = id): ScreenCard => ({
  id, ids: [id], kind: "ui", title, startMs, endMs: startMs + 8000, highlights: [], lines: [], moreRows: 0, folded, raw: "", layout: "",
});
const digest = (over: Partial<Digest> = {}): Digest => ({
  contentType: "meeting", title: "T", summary: [], outcome: null, speakers: [], perspectives: [],
  chapters: [chapter("One", 0, 60_000), chapter("Two", 60_000, 120_000), chapter("Three", 120_000, 180_000)],
  decisions: [], actions: [], questions: [], disagreements: [], figures: [], risks: [], concepts: [], diagram: null, screenUses: [], ...over,
});

test("a moment belongs to the last topic that has started; before the first it belongs to the first", () => {
  const chapters = digest().chapters;
  assert.equal(topicIndex(chapters, 0), 0);
  assert.equal(topicIndex(chapters, 59_999), 0);
  assert.equal(topicIndex(chapters, 60_000), 1);
  assert.equal(topicIndex(chapters, 179_000), 2);
  assert.equal(topicIndex(chapters, null), null);
  assert.equal(topicIndex([], 5), null);
  assert.equal(topicIndex([chapter("Late", 30_000, 60_000)], 1000), 0);
});

test("a screen that appears just before a boundary moves into the topic that is starting; one well before it does not", () => {
  const topics = buildStoryline(digest(), [card("near", 60_000 - BOUNDARY_SLACK_MS), card("far", 60_000 - BOUNDARY_SLACK_MS - 1), card("exact", 120_000)]);
  const titles = (index: number) => topics[index].rows.map((row) => (row.kind === "screen" ? row.card.id : row.kind));
  assert.deepEqual(titles(0), ["far"]);
  assert.deepEqual(titles(1), ["near"]);
  assert.deepEqual(titles(2), ["exact"]);
});

test("screens with nothing readable fold into one line per topic and are not counted as screens", () => {
  const [one, two] = buildStoryline(digest(), [card("a", 1000), card("blank1", 10_000, true), card("blank2", 20_000, true), card("b", 70_000)]);
  assert.deepEqual(one.rows.map((row) => row.kind), ["screen", "folded"]);
  const folded = one.rows[1];
  assert.equal(folded.kind === "folded" ? folded.cards.length : 0, 2);
  assert.equal(one.counts.screens, 1);
  assert.equal(two.counts.screens, 1);
});

test("answered questions, ideas and figures sit in their topic in time order; open questions and actions are only counted", () => {
  const question = (text: string, startMs: number, answered: boolean) => ({ question: text, askedBy: null, startMs, askedSpanId: "q", answered, answer: answered ? "yes" : null, answerMs: answered ? startMs + 3000 : null, answerSpanId: null });
  const topics = buildStoryline(
    digest({
      questions: [question("answered", 65_000, true), question("open", 70_000, false)],
      concepts: [{ term: "Idea", explanation: "x", spanIds: [], basis: "confirmed", startMs: 62_000 }],
      figures: [{ value: "5", what: "five", spanId: "f", startMs: 100_000 }],
      actions: [{ task: "Do it", owner: null, due: null, agreed: false, actionId: null, spanIds: [], basis: "confirmed", startMs: 90_000 }],
    }),
    [card("shown", 75_000)],
  );
  const two = topics[1];
  assert.deepEqual(two.rows.map((row) => row.kind), ["idea", "answer", "screen", "figure"]);
  assert.deepEqual(two.counts, { screens: 1, answered: 1, open: 1, actions: 1, ideas: 1 });
  assert.ok(!two.rows.some((row) => row.kind === "answer" && row.question.question === "open"));
});

test("no chapters gives no storyline, and an item with no time is left to its own section", () => {
  assert.deepEqual(buildStoryline(digest({ chapters: [] }), [card("a", 0)]), []);
  const topics = buildStoryline(digest({ figures: [{ value: "5", what: "five", spanId: "f", startMs: null }] }), []);
  assert.ok(topics.every((topic) => topic.rows.length === 0));
});
