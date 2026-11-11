import assert from "node:assert/strict";
import test from "node:test";
import {
  TRANSCRIPT_ACCEPT,
  TRANSCRIPT_TYPES,
  choosePrimary,
  isSubtitleFile,
  isTranscriptFile,
  mediaTypeOf,
  pickPrimary,
} from "@/lib/mcp/upload";

const WORD = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

const file = (name: string, type = "") => new File(["x"], name, { type });

test("transcript extensions are recognised in any case, and nothing else is", () => {
  for (const name of ["talk.srt", "talk.VTT", "notes.txt", "notes.text", "run.log", "a.md", "a.markdown", "brief.docx", "brief.pdf", "page.html", "page.HTM", "old.rtf", "data.json"]) {
    assert.equal(isTranscriptFile(name), true, name);
  }
  for (const name of ["call.mp4", "voice.m4a", "deck.pptx", "sheet.xlsx", "shot.png", "archive.zip", "noextension", "constructor"]) {
    assert.equal(isTranscriptFile(name), false, name);
  }
  assert.equal(isTranscriptFile(".srt"), false); // a bare extension is not a file name
});

test("only SRT and VTT are subtitles, which are always the transcript", () => {
  assert.equal(isSubtitleFile("a.srt"), true);
  assert.equal(isSubtitleFile("a.VTT"), true);
  assert.equal(isSubtitleFile("a.txt"), false);
  assert.equal(isSubtitleFile("a.mp4"), false);
});

test("the accept attribute lists every transcript extension", () => {
  const listed = TRANSCRIPT_ACCEPT.split(",").map((item) => item.slice(1)).sort();
  assert.deepEqual(listed, Object.keys(TRANSCRIPT_TYPES).sort());
  assert.ok(TRANSCRIPT_ACCEPT.includes(".srt") && TRANSCRIPT_ACCEPT.includes(".vtt"));
});

test("a transcript is sent with its own media type", () => {
  assert.equal(mediaTypeOf(file("talk.srt")), "application/x-subrip");
  assert.equal(mediaTypeOf(file("talk.vtt")), "text/vtt");
  assert.equal(mediaTypeOf(file("notes.log")), "text/plain");
  assert.equal(mediaTypeOf(file("notes.md")), "text/markdown");
  assert.equal(mediaTypeOf(file("brief.docx")), WORD);
  assert.equal(mediaTypeOf(file("brief.pdf")), "application/pdf");
  assert.equal(mediaTypeOf(file("page.htm")), "text/html");
  assert.equal(mediaTypeOf(file("old.rtf")), "application/rtf");
  assert.equal(mediaTypeOf(file("data.json")), "application/json");
});

test("recordings keep their media types, and an unknown name falls back to the browser's", () => {
  assert.equal(mediaTypeOf(file("call.mp4", "video/mp4")), "video/mp4");
  assert.equal(mediaTypeOf(file("voice.m4a")), "audio/mp4");
  assert.equal(mediaTypeOf(file("mystery", "text/x-odd")), "text/x-odd");
  assert.equal(mediaTypeOf(file("mystery")), "application/octet-stream");
});

test("the primary input is a subtitle first, then a recording, then the first transcript document", () => {
  const doc = file("brief.docx");
  const txt = file("notes.txt");
  const recording = file("call.mp4", "video/mp4");
  const srt = file("talk.srt");
  assert.equal(pickPrimary([]), null);
  assert.equal(pickPrimary([file("deck.pptx")]), null);
  assert.equal(pickPrimary([doc, txt]), doc);
  assert.equal(pickPrimary([file("deck.pptx"), txt]), txt);
  assert.equal(pickPrimary([doc, recording]), recording);
  assert.equal(pickPrimary([recording, srt]), srt);
});

test("a picked transcript with no recording becomes the primary input; the rest stay for Context", () => {
  const doc = file("brief.docx");
  const deck = file("deck.pptx");
  const choice = choosePrimary(null, [deck, doc]);
  assert.equal(choice.primary, doc);
  assert.equal(choice.displaced, null);
  assert.deepEqual(choice.rest, [deck]);
});

test("a document never replaces a recording that is already the primary input", () => {
  const recording = file("call.mp4", "video/mp4");
  const doc = file("notes.txt");
  const choice = choosePrimary(recording, [doc]);
  assert.equal(choice.primary, recording);
  assert.equal(choice.displaced, null);
  assert.deepEqual(choice.rest, [doc]);
});

test("a document never replaces an existing transcript either; the new one is reference", () => {
  const first = file("notes.txt");
  const second = file("minutes.md");
  const choice = choosePrimary(first, [second]);
  assert.equal(choice.primary, first);
  assert.deepEqual(choice.rest, [second]);
});

test("a recording replaces a transcript, which goes back to Context", () => {
  const transcript = file("notes.txt");
  const recording = file("call.mp4", "video/mp4");
  const choice = choosePrimary(transcript, [recording]);
  assert.equal(choice.primary, recording);
  assert.equal(choice.displaced, transcript);
  assert.deepEqual(choice.rest, []);
});

test("a subtitle file replaces a recording, and extra transcripts are left in the rest", () => {
  const recording = file("call.mp4", "video/mp4");
  const first = file("talk.srt");
  const second = file("talk-2.vtt");
  const choice = choosePrimary(recording, [first, second]);
  assert.equal(choice.primary, first);
  assert.equal(choice.displaced, recording);
  assert.deepEqual(choice.rest, [second]);
});

test("a pick with nothing usable leaves the current primary input alone", () => {
  const current = file("notes.txt");
  const choice = choosePrimary(current, [file("deck.pptx"), file("shot.png", "image/png")]);
  assert.equal(choice.primary, current);
  assert.equal(choice.displaced, null);
  assert.equal(choice.rest.length, 2);
});

test("an issued upload target is read from the task-less submit_meeting result", async () => {
  const { parseIssuedUpload } = await import("@/lib/mcp/upload");
  const ok = {
    content: [{ type: "text", text: JSON.stringify({ status: "upload_target_issued", upload_url: "https://s3.example/x?sig=1", object_key: "uploads/u-abc-1/notes.vtt", headers: { "Content-Type": "text/vtt" } }) }],
  };
  assert.deepEqual(parseIssuedUpload(ok), { url: "https://s3.example/x?sig=1", headers: { "Content-Type": "text/vtt" }, objectKey: "uploads/u-abc-1/notes.vtt" });
  const refused = { isError: true, content: [{ type: "text", text: JSON.stringify({ error: "The transcript is larger than 50 MB." }) }] };
  assert.throws(() => parseIssuedUpload(refused), /larger than 50 MB/);
  assert.throws(() => parseIssuedUpload({ content: [{ type: "text", text: "{}" }] }), /did not issue/);
});

test("the refusals the server gives before an upload reach the person unchanged", async () => {
  const { friendlyError } = await import("@/lib/present");
  assert.equal(friendlyError("The transcript is larger than 50 MB."), "The transcript is larger than 50 MB.");
  assert.equal(friendlyError("The recording is larger than 5 GB."), "The recording is larger than 5 GB.");
});
