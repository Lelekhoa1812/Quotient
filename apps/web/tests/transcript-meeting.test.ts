import assert from "node:assert/strict";
import test from "node:test";
import { emptyGraph, mergeGraph, parseGraph, parseMeetingStatus, parseModelProvider, parseSource, transcriptNotice } from "@/lib/graph";
import type { MeetingSource } from "@/lib/types";

const TRANSCRIPT = {
  kind: "transcript",
  format: "srt",
  timings: "exact",
  speakers: 5,
  words: 4210,
  title: "Quarterly review",
  truncated: false,
};

test("source is null for a recording and for anything that is not a transcript", () => {
  for (const odd of [null, undefined, "transcript", 3, [], {}, { kind: "recording" }, { kind: "Transcript" }, { format: "srt" }]) {
    assert.equal(parseSource(odd), null, JSON.stringify(odd));
  }
});

test("a transcript source is read with its facts, and missing or odd values stay safe", () => {
  assert.deepEqual(parseSource(TRANSCRIPT), {
    kind: "transcript",
    format: "SRT",
    timings: "exact",
    speakers: 5,
    words: 4210,
    title: "Quarterly review",
    truncated: false,
  });
  assert.deepEqual(parseSource({ kind: "transcript", timings: "guessed", speakers: -2, words: "many", format: 9, title: null, truncated: "yes" }), {
    kind: "transcript",
    format: "",
    timings: "exact",
    speakers: 0,
    words: 0,
    title: "",
    truncated: false,
  });
  assert.equal(parseSource({ kind: "transcript", timings: "estimated", speakers: 2.7, words: 10.9 })?.timings, "estimated");
  assert.equal(parseSource({ kind: "transcript", timings: "estimated", speakers: 2.7, words: 10.9 })?.speakers, 2);
  assert.equal(parseSource({ kind: "transcript", words: 10.9 })?.words, 10);
});

test("the model provider is bedrock or nim; anything else is unknown", () => {
  assert.equal(parseModelProvider("nim"), "nim");
  assert.equal(parseModelProvider("bedrock"), "bedrock");
  for (const odd of ["NIM", "openai", "", null, 1, undefined]) {
    assert.equal(parseModelProvider(odd), null, String(odd));
  }
});

test("get_meeting carries source and model_provider; a meeting without them has null", () => {
  const status = parseMeetingStatus(
    { meeting: { meeting_id: "M1", status: "ready", source: TRANSCRIPT, model_provider: "nim" } },
    "M1",
  );
  assert.deepEqual(status.source, parseSource(TRANSCRIPT));
  assert.equal(status.modelProvider, "nim");

  const recording = parseMeetingStatus({ meeting: { meeting_id: "M2", status: "ready", source: null } }, "M2");
  assert.equal(recording.source, null);
  assert.equal(recording.modelProvider, null);
});

test("read_graph carries the transcript source; playback stays empty and captions null when timings are estimated", () => {
  const page = parseGraph(
    {
      graph: {
        spans: [],
        source: { ...TRANSCRIPT, timings: "estimated" },
        model_provider: "bedrock",
        playback: "",
        captions: null,
      },
    },
    "M3",
  );
  assert.equal(page.source?.timings, "estimated");
  assert.equal(page.modelProvider, "bedrock");
  assert.deepEqual(page.playback, { original: "", burned: "", sidecar: "" });
  assert.equal(page.captions, "");
});

test("a recording graph has no source, and an empty graph reads as a recording", () => {
  const page = parseGraph({ graph: { spans: [], playback: { original: "https://media.example/a.mp4" } } }, "M4");
  assert.equal(page.source, null);
  assert.equal(page.modelProvider, null);
  assert.equal(emptyGraph().source, null);
});

test("merging pages keeps the source and provider that any page carried", () => {
  const first = parseGraph({ graph: { source: TRANSCRIPT, model_provider: "nim" } }, "M5");
  const later = parseGraph({ graph: { spans: [] } }, "M5");
  const merged = mergeGraph(first, later);
  assert.equal(merged.source?.format, "SRT");
  assert.equal(merged.modelProvider, "nim");
  assert.equal(mergeGraph(emptyGraph(), later).source, null);
});

test("the transcript notice names the format, speakers and words", () => {
  const source = parseSource(TRANSCRIPT) as MeetingSource;
  assert.deepEqual(transcriptNotice(source), { line: "Transcript · SRT · 5 speakers · 4,210 words", estimate: null });
});

test("the notice says when times are estimated, and reads singular counts correctly", () => {
  const source = parseSource({ ...TRANSCRIPT, timings: "estimated", speakers: 1, words: 1 }) as MeetingSource;
  assert.deepEqual(transcriptNotice(source), {
    line: "Transcript · SRT · 1 speaker · 1 word",
    estimate: "Times are estimated from word count.",
  });
});

test("the notice leaves out a format or counts that are not known", () => {
  const source = parseSource({ kind: "transcript" }) as MeetingSource;
  assert.deepEqual(transcriptNotice(source), { line: "Transcript", estimate: null });
});

test("progress steps read a transcript instead of transcribing a recording", async () => {
  const { analysisStepIndex, analysisStepLabels, friendlyError } = await import("@/lib/present");
  assert.equal(analysisStepLabels(true)[0], "Reading the transcript");
  assert.equal(analysisStepLabels(false)[0], "Transcribing the recording");
  assert.equal(analysisStepIndex("Fetching the transcript"), 0);
  assert.equal(analysisStepIndex("Reading the transcript"), 0);
  assert.equal(friendlyError("This PDF is password-protected."), "This PDF is password-protected.");
  assert.equal(friendlyError("boom"), "Something went wrong. Please try again.");
});
