import assert from "node:assert/strict";
import test from "node:test";
import { chapterAt, dueText, hasOutcomes, parseDigest, promisedByOwner } from "@/lib/digest";

test("a value that is not an object is not a digest", () => {
  assert.equal(parseDigest(null), null);
  assert.equal(parseDigest("text"), null);
  assert.equal(parseDigest([1]), null);
});

test("unknown basis falls back to transcript, bad content types to other, and chapters come back in time order", () => {
  const digest = parseDigest({
    content_type: "podcast",
    title: "T",
    summary: [{ text: "One.", span_ids: ["s1"], basis: "weird", start_ms: 1000 }],
    chapters: [
      { title: "Second", gist: "g", start_span_id: "b", start_ms: 9000, end_ms: 12000 },
      { title: "First", gist: "g", start_span_id: "a", start_ms: 0, end_ms: 9000 },
    ],
  });
  assert.ok(digest);
  assert.equal(digest.contentType, "other");
  assert.equal(digest.summary[0].basis, "transcript");
  assert.deepEqual(digest.chapters.map((chapter) => chapter.title), ["First", "Second"]);
});

test("items missing their text or required id are dropped, not padded", () => {
  const digest = parseDigest({
    decisions: [{ statement: "", status: "agreed" }, { statement: "Ship Friday", status: "agreed", decided_by: "spk_1", basis: "likely", start_ms: 4000 }],
    open_questions: [{ question: "Who?" }, { question: "When?", asked_span_id: "s2", answered: true, answer: "Monday", answer_ms: 5000 }],
    key_figures: [{ value: "4", what: "departments" }, { value: "4", what: "departments", span_id: "s3", start_ms: 7000 }],
    disagreements: [{ topic: "Scope", positions: [{ position: "More", speaker: "spk_0" }] }],
  });
  assert.ok(digest);
  assert.deepEqual(digest.decisions.map((row) => [row.statement, row.by, row.basis]), [["Ship Friday", "spk_1", "likely"]]);
  assert.deepEqual(digest.questions.map((row) => [row.question, row.answered, row.answerMs]), [["When?", true, 5000]]);
  assert.equal(digest.figures.length, 1);
  assert.equal(digest.disagreements.length, 0); // one position is not a disagreement
});

test("a partial reply is carried on an unanswered question", () => {
  const digest = parseDigest({ open_questions: [{ question: "Choice?", asked_span_id: "s1", answered: false, answer: "Parents must be involved", answer_ms: 3000 }] });
  assert.ok(digest);
  assert.deepEqual([digest.questions[0].answered, digest.questions[0].answer, digest.questions[0].answerMs], [false, "Parents must be involved", 3000]);
});

test("the current chapter is the last one that has started; nothing before the first", () => {
  const chapters = [{ title: "A", gist: "", startMs: 1000, endMs: 5000, startSpanId: "a" }, { title: "B", gist: "", startMs: 5000, endMs: 9000, startSpanId: "b" }];
  assert.equal(chapterAt(chapters, 0), null);
  assert.equal(chapterAt(chapters, 4999)?.title, "A");
  assert.equal(chapterAt(chapters, 5000)?.title, "B");
});

test("only decisions, actions, questions and disagreements count as outcomes", () => {
  assert.equal(hasOutcomes(parseDigest({ summary: [{ text: "x", span_ids: ["s"], start_ms: 0 }] })!), false);
  assert.equal(hasOutcomes(parseDigest({ actions: [{ task: "Send it", agreed: true }] })!), true);
});

test("a due phrase is shown only when it names a time", () => {
  assert.equal(dueText("Monday"), "Monday");
  assert.equal(dueText("in the next half hour or so"), "in the next half hour or so");
  assert.equal(dueText("by the 3rd of November"), "by the 3rd of November");
  for (const said of ["next sprint", "by noon", "ASAP", "in a fortnight", "by midnight", "immediately", "in two weeks", "several quarters", "by Fri", "３日", "٣ أيام"]) assert.equal(dueText(said), said);
  assert.equal(dueText("next"), null);
  assert.equal(dueText("later"), null);
  assert.equal(dueText(null), null);
});

test("an action is a promise only when its owner said they would do it in a line it cites", () => {
  const line = (id: string, speaker: string | null, text: string) => ({ id, speaker_hypothesis_id: speaker, text, raw_text: text });
  const spans = [line("a", "spk_1", "i will send you a video"), line("b", "spk_0", "maddy can you send the notes"), line("c", "spk_2", "sure thing")];
  assert.equal(promisedByOwner({ owner: "spk_1", spanIds: ["a"] }, spans), true);
  assert.equal(promisedByOwner({ owner: "spk_2", spanIds: ["b", "c"] }, spans), false); // agreed to a request, not a first-person promise
  assert.equal(promisedByOwner({ owner: "spk_1", spanIds: ["b"] }, spans), false); // did not speak the cited line
  assert.equal(promisedByOwner({ owner: null, spanIds: ["a"] }, spans), false);
  const said = (text: string) => promisedByOwner({ owner: "spk_1", spanIds: ["x"] }, [line("x", "spk_1", text)]);
  for (const promise of ["I'm gonna send it", "We’ll send it", "I can send it", "We will not only fix it but test it"]) assert.equal(said(promise), true, promise);
  for (const refusal of ["I can't make Friday", "We will not do that", "I can’t"]) assert.equal(said(refusal), false, refusal);
});
