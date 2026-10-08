import assert from "node:assert/strict";
import test from "node:test";
import { DIMENSIONS } from "@/lib/types";
import {
  claimStatusText,
  decisionStatusText,
  dimensionTitle,
  durationText,
  friendlyError,
  speakerName,
  stanceText,
  analysisStepIndex,
  dimensionQuestion,
  isOpenPointTopic,
} from "@/lib/present";

const MACHINE = /[a-z]+_[a-z_]+/;

test("every dimension reads as ordinary words, never a machine value", () => {
  for (const dimension of DIMENSIONS) {
    const text = dimensionTitle(dimension);
    assert.ok(text.length > 0);
    assert.doesNotMatch(text, MACHINE, dimension);
  }
});

test("decision and claim statuses translate without leaking snake_case", () => {
  for (const value of ["aligned", "needs_discussion", "disagreed", "shelved"] as const) {
    assert.doesNotMatch(decisionStatusText(value), MACHINE);
  }
  assert.equal(decisionStatusText(null), "Outcome not stated");
  for (const value of ["supported", "unresolved", "contradicted", "numeric_failed", "incomplete", "pending", "unknown"]) {
    assert.doesNotMatch(claimStatusText(value), MACHINE);
  }
  assert.equal(stanceText("conflicts"), "Conflicts with other evidence");
});

test("an unknown value falls back to neutral wording rather than the raw code", () => {
  assert.equal(claimStatusText("brand_new_status"), "Not settled");
  assert.equal(stanceText("weird_value"), "Not settled");
});

test("speakers never show a worker hypothesis id", () => {
  assert.equal(speakerName("Alex", "h1"), "Alex");
  assert.equal(speakerName(null, "hypothesis-0"), "Speaker 1");
  assert.equal(speakerName(null, "hypothesis-2"), "Speaker 3");
  assert.equal(speakerName(null, null), "Unnamed speaker");
  assert.equal(speakerName("  ", "h"), "Unnamed speaker");
});

test("durations read naturally", () => {
  assert.equal(durationText(45_000), "45 s");
  assert.equal(durationText(80_000), "1 min 20 s");
  assert.equal(durationText(20 * 60_000), "20 min");
  assert.equal(durationText(3_900_000), "1 h 5 min");
});

test("server failures become sentences, never raw error text", () => {
  assert.doesNotMatch(friendlyError("SchemaRejected: Additional properties are not allowed ('origin' was unexpected)"), /origin|Schema/);
  assert.equal(friendlyError(null), "Something went wrong. Please try again.");
  assert.match(friendlyError("blocked by our content filters"), /declined/);
});

test("a bad-media failure never exposes paths or commands, old or new", () => {
  const old = "CalledProcessError: Command '['ffprobe', '-v', 'error', '/Users/someone/derivatives/x.mp4']' returned non-zero exit status 1.";
  assert.equal(friendlyError(old), "This file is not a readable audio or video recording.");
  assert.doesNotMatch(friendlyError(old), /Users|ffprobe/);
  assert.equal(friendlyError("The recording could not be found."), "The recording could not be found.");
});

test("every worker phase message maps to the right step, and unknown ones do not guess", () => {
  const cases: [string, number][] = [
    ["Preparing the media and building the transcript", 0],
    ["Streaming audio transcription; visual analysis is unavailable on local MinIO", 0],
    ["Compacting transcript spans", 1],
    ["Checking audio against visual evidence", 1],
    ["Extracting claims from the transcript", 1],
    ["Checking transcript coverage", 2],
    ["Analyzing all ten evidence lenses", 3],
    ["Building the evidence-backed brief", 3],
    ["Summarizing the available evidence", 3],
    ["Extracting and grounding follow-up actions", 3],
    ["Building charts and checking publish readiness", 4],
    ["Something new the worker added", -1],
  ];
  for (const [message, step] of cases) assert.equal(analysisStepIndex(message), step, message);
});

test("question and gap topics never claim something is unanswered", () => {
  assert.equal(dimensionTitle("question"), "Questions raised");
  assert.ok(!/unanswered|still open/i.test(dimensionQuestion("question") + dimensionQuestion("gap")));
  assert.equal(isOpenPointTopic("question"), true);
  assert.equal(isOpenPointTopic("decision"), false);
});
