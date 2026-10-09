import assert from "node:assert/strict";
import test from "node:test";
import {
  ACCEPTED_TYPES,
  MAX_FILE_BYTES,
  MAX_ITEMS,
  MAX_NOTE_CHARS,
  MAX_TOTAL_BYTES,
  buildPrepareArgs,
  classifyFile,
  REASON_NAME,
  cleanForSave,
  contextBadge,
  formatBytes,
  parsePrepareResult,
  planAdditions,
  planNote,
  runPool,
  sameContext,
  skippedNotice,
  splitRecordings,
  toUploads,
  totalsLine,
  withNoteText,
  type ContextItem,
} from "@/lib/context";
import { parseMeetingContext, parseMeetingStatus } from "@/lib/graph";

const MB = 1024 * 1024;

test("every accepted extension is classified, in any case, with its kind and media type", () => {
  const expected: Record<string, string> = {
    pdf: "document", docx: "document", pptx: "slides", xlsx: "table", xls: "table", csv: "table",
    json: "code", xml: "code", html: "document", htm: "document", md: "document", markdown: "document",
    txt: "document", epub: "document",
  };
  assert.deepEqual(Object.keys(ACCEPTED_TYPES).sort(), Object.keys(expected).sort());
  for (const [extension, kind] of Object.entries(expected)) {
    for (const name of [`brief.${extension}`, `BRIEF.${extension.toUpperCase()}`]) {
      const verdict = classifyFile({ name, type: "", size: 1000 });
      assert.equal(verdict.ok, true, name);
      if (verdict.ok) {
        assert.equal(verdict.kind, kind, name);
        assert.equal(verdict.mediaType, ACCEPTED_TYPES[extension].mediaType, name);
      }
    }
  }
});

test("the extension wins over an odd browser-reported type", () => {
  const verdict = classifyFile({ name: "numbers.csv", type: "application/vnd.ms-excel", size: 10 });
  assert.equal(verdict.ok && verdict.mediaType, "text/csv");
  assert.equal(classifyFile({ name: "slides.pptx", type: "application/zip", size: 10 }).ok, true);
});

test("only the extension decides: a known type on a name the service would refuse is refused here too", () => {
  for (const file of [
    { name: "notes", type: "text/plain" },
    { name: "data.bin", type: "application/pdf" },
    { name: "notes", type: "application/pdf; charset=binary" },
    { name: "notes", type: "" },
  ]) {
    const verdict = classifyFile({ ...file, size: 5 });
    assert.equal(verdict.ok, false, file.name + " " + file.type);
    assert.deepEqual(verdict.ok ? null : verdict.reason, "This type of file isn't supported");
  }
  assert.equal(classifyFile({ name: "REPORT.PDF", type: "", size: 5 }).ok, true);
});

test("a recording is found by its extension when the browser reports no type", async () => {
  const { isRecording } = await import("@/lib/context");
  assert.equal(isRecording({ name: "standup.mkv", type: "" }), true);
  assert.equal(isRecording({ name: "standup.mp4", type: "video/mp4" }), true);
  assert.equal(isRecording({ name: "design.docx", type: "" }), false);
});

test("images are refused with their own sentence", () => {
  for (const file of [
    { name: "shot.png", type: "image/png" },
    { name: "photo.JPG", type: "" },
    { name: "logo.svg", type: "image/svg+xml" },
    { name: "scan", type: "image/jpeg" },
    { name: "pic.webp", type: "image/webp" },
    { name: "phone.heic", type: "" },
  ]) {
    const verdict = classifyFile({ ...file, size: 100 });
    assert.equal(verdict.ok, false, file.name);
    if (!verdict.ok) {
      assert.equal(verdict.reason, "Images aren't supported yet", file.name);
      assert.equal(verdict.code, "image");
    }
  }
});

test("recordings, archives and programs are refused with the general sentence", () => {
  for (const file of [
    { name: "call.mp4", type: "video/mp4" },
    { name: "call.mp3", type: "audio/mpeg" },
    { name: "bundle.zip", type: "application/zip" },
    { name: "setup.exe", type: "application/x-msdownload" },
    { name: "data.7z", type: "" },
    { name: "old.doc", type: "application/msword" },
  ]) {
    const verdict = classifyFile({ ...file, size: 100 });
    assert.equal(verdict.ok, false, file.name);
    if (!verdict.ok) assert.equal(verdict.reason, "This type of file isn't supported", file.name);
  }
});

test("size limits: 25 MB passes, one byte more does not, and an empty file is refused", () => {
  assert.equal(classifyFile({ name: "a.pdf", type: "", size: MAX_FILE_BYTES }).ok, true);
  const big = classifyFile({ name: "a.pdf", type: "", size: MAX_FILE_BYTES + 1 });
  assert.equal(big.ok ? null : big.reason, "Larger than 25 MB");
  const empty = classifyFile({ name: "a.pdf", type: "", size: 0 });
  assert.equal(empty.ok ? null : empty.code, "empty");
});

test("a rejected file stays in the list with its reason and counts against nothing", () => {
  const plan = planAdditions([], [
    { name: "ok.pdf", type: "application/pdf", size: 2 * MB },
    { name: "shot.png", type: "image/png", size: MB },
    { name: "huge.pdf", type: "application/pdf", size: 30 * MB },
  ]);
  assert.deepEqual(plan.items.map((item) => [item.name, item.status, item.reason]), [
    ["ok.pdf", "ready", ""],
    ["shot.png", "rejected", "Images aren't supported yet"],
    ["huge.pdf", "rejected", "Larger than 25 MB"],
  ]);
  assert.equal(totalsLine(plan.items), "1 item · 2 MB");
  assert.equal(plan.notice, "");
});

test("adding stops at 20 items, and at 100 MB in total, with a plain message", () => {
  const files = Array.from({ length: 23 }, (_, index) => ({ name: `f${index}.txt`, type: "text/plain", size: 100 }));
  const full = planAdditions([], files);
  assert.equal(full.items.length, MAX_ITEMS);
  assert.equal(full.notice, "You can add up to 20 items. 3 files were not added.");
  assert.equal(planAdditions(full.items, [{ name: "more.txt", type: "", size: 1 }]).items.length, 0);

  const heavy = Array.from({ length: 5 }, (_, index) => ({ name: `h${index}.pdf`, type: "", size: 24 * MB }));
  const capped = planAdditions([], heavy);
  assert.equal(capped.items.length, 4);
  assert.equal(capped.notice, "That would go over 100 MB in total. 1 file was not added.");
  assert.equal(MAX_TOTAL_BYTES, 104_857_600); // the service's 100 MB, in bytes; a typo in either place must fail here
});

test("the same file added twice is skipped and said so", () => {
  const first = planAdditions([], [{ name: "a.pdf", type: "", size: 10 }]);
  const again = planAdditions(first.items, [{ name: "a.pdf", type: "", size: 10 }]);
  assert.equal(again.items.length, 0);
  assert.equal(again.notice, "1 file was already added.");
});

test("pasted notes are named Pasted note N, then the typed title", () => {
  const first = planNote([], "", "Glossary: QBR means quarterly business review.");
  assert.equal(first.item?.name, "Pasted note 1");
  const second = planNote([first.item as ContextItem], "   ", "More text");
  assert.equal(second.item?.name, "Pasted note 2");
  const titled = planNote([], "  Billing / glossary: v2?  ", "text");
  assert.equal(titled.item?.name, "Billing - glossary- v2-");
  const clash = planNote([titled.item as ContextItem], "Billing - glossary- v2-.md", "again");
  assert.equal(clash.item?.name, "Billing - glossary- v2- 2");
});

test("a note becomes a Markdown file; an empty or oversized note is not addable", () => {
  const added = planNote([], "Brief", "héllo");
  const item = added.item as ContextItem;
  assert.equal(item.kind, "note");
  assert.equal(item.chars, 5);
  assert.equal(item.size, 6);
  const [upload] = toUploads([item]);
  assert.equal(upload.file.name, "Brief.md");
  assert.equal(upload.file.type, "text/markdown");
  assert.equal(upload.file.size, 6);
  assert.equal(upload.mediaType, "text/markdown");

  assert.equal(planNote([], "x", "   \n ").item, null);
  assert.equal(planNote([], "x", "a".repeat(MAX_NOTE_CHARS + 1)).item, null);
  assert.equal(planNote([], "x", "a".repeat(MAX_NOTE_CHARS)).item?.chars, MAX_NOTE_CHARS);
  const edited = withNoteText(item, "longer text");
  assert.deepEqual([edited.chars, edited.size], [11, 11]);
});

test("prepare_context arguments: one entry per file, in order, 1 to 20", () => {
  const note = planNote([], "Brief", "hello").item as ContextItem;
  const file = new File(["abc"], "deck.pptx", { type: "" });
  const picked = planAdditions([note], [file]).items;
  const args = buildPrepareArgs(toUploads([note, ...picked]));
  assert.deepEqual(args, {
    files: [
      { filename: "Brief.md", media_type: "text/markdown", byte_size: 5 },
      {
        filename: "deck.pptx",
        media_type: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        byte_size: 3,
      },
    ],
  });
  assert.throws(() => buildPrepareArgs([]), RangeError);
  const many = Array.from({ length: 21 }, () => ({ id: "x", file, mediaType: "text/plain" }));
  assert.throws(() => buildPrepareArgs(many), RangeError);
  assert.equal(buildPrepareArgs(many.slice(0, 20)).files.length, 20);
});

test("rejected items are never uploaded", () => {
  const plan = planAdditions([], [{ name: "a.png", type: "image/png", size: 5 }, new File(["x"], "b.txt")]);
  assert.equal(toUploads(plan.items).length, 1);
});

function target(index: number, extra: Record<string, unknown> = {}) {
  return {
    index,
    filename: `f${index}`,
    upload_url: `https://bucket.example/put/${index}`,
    method: "PUT",
    headers: { "Content-Type": "text/plain" },
    object_key: `key/${index}`,
    ...extra,
  };
}

test("prepare_context result: batch, ordered targets, structured or text content", () => {
  const body = { batch_id: "B1", uploads: [target(1), target(0)] };
  for (const raw of [body, { structuredContent: body }, { content: [{ type: "text", text: JSON.stringify(body) }] }]) {
    const outcome = parsePrepareResult(raw, 2);
    assert.equal(outcome.ok, true);
    if (outcome.ok) {
      assert.equal(outcome.batchId, "B1");
      assert.equal(outcome.uploads[0]?.url, "https://bucket.example/put/0");
      assert.deepEqual(outcome.uploads[1]?.headers, { "Content-Type": "text/plain" });
      assert.equal(outcome.uploads[1]?.objectKey, "key/1");
    }
  }
});

test("prepare_context errors and odd results are plain failures, never a guess", () => {
  assert.deepEqual(parsePrepareResult({ error: "Too many files" }, 1), { ok: false, error: "Too many files" });
  assert.deepEqual(parsePrepareResult({ structuredContent: { error: "Quota used up" } }, 1), { ok: false, error: "Quota used up" });
  assert.deepEqual(parsePrepareResult({ isError: true, content: [{ type: "text", text: "Not allowed" }] }, 1), { ok: false, error: "Not allowed" });
  for (const raw of [null, undefined, "x", 7, [], {}, { batch_id: 4 }, { uploads: [] }]) {
    const outcome = parsePrepareResult(raw, 1);
    assert.equal(outcome.ok, false);
  }
  // A target that is not an https PUT, or whose index is out of range, leaves that file without a target.
  const odd = parsePrepareResult({ batch_id: "B", uploads: [target(0, { method: "POST" }), target(1, { upload_url: "ftp://x" }), target(7), "junk", null] }, 2);
  assert.equal(odd.ok, true);
  if (odd.ok) assert.deepEqual(odd.uploads, [null, null]);
});

test("uploads run two at a time", async () => {
  let running = 0;
  let peak = 0;
  const done: number[] = [];
  await runPool([1, 2, 3, 4, 5, 6], 2, async (item) => {
    running += 1;
    peak = Math.max(peak, running);
    await new Promise((resolve) => setTimeout(resolve, 5));
    running -= 1;
    done.push(item);
  });
  assert.equal(peak, 2);
  assert.deepEqual([...done].sort(), [1, 2, 3, 4, 5, 6]);
  await runPool([], 2, async () => assert.fail("no work"));
});

test("the skipped notice names what the meeting started without", () => {
  assert.equal(skippedNotice([]), "");
  assert.equal(skippedNotice(["a.pdf"]), "The meeting started without a.pdf, which couldn't be uploaded.");
  assert.equal(
    skippedNotice(["a.pdf", "Pasted note 1"]),
    "The meeting started without 2 context items that couldn't be uploaded: a.pdf, Pasted note 1.",
  );
});

test("sizes and totals read plainly", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(1536), "1.5 KB");
  assert.equal(formatBytes(820 * 1024), "820 KB");
  assert.equal(formatBytes(4.2 * MB), "4.2 MB");
  assert.equal(formatBytes(25 * MB), "25 MB");
  assert.equal(formatBytes(NaN), "0 B");
  const items = planAdditions([], [
    { name: "a.pdf", type: "", size: 3 * MB },
    { name: "b.csv", type: "", size: 1.2 * MB },
    { name: "c.txt", type: "", size: 0.5 * MB },
  ]).items;
  assert.equal(totalsLine(items), "3 items · 4.7 MB");
  assert.equal(totalsLine([]), "");
});

test("recordings are told apart from reference files", () => {
  const files = [
    new File(["x"], "call.mp4", { type: "video/mp4" }),
    new File(["x"], "voice.m4a"),
    new File(["x"], "deck.pptx"),
    new File(["x"], "shot.png", { type: "image/png" }),
  ];
  const { recordings, others } = splitRecordings(files);
  assert.deepEqual(recordings.map((file) => file.name), ["call.mp4", "voice.m4a"]);
  assert.deepEqual(others.map((file) => file.name), ["deck.pptx", "shot.png"]);
});

test("saving drops rejected rows, trims the purpose and counts only what is kept", () => {
  const items = planAdditions([], [new File(["x"], "a.txt"), { name: "b.png", type: "image/png", size: 4 }]).items;
  const saved = cleanForSave({ purpose: "  Why  ", items });
  assert.equal(saved.purpose, "Why");
  assert.deepEqual(saved.items.map((item) => item.name), ["a.txt"]);
  assert.equal(sameContext(saved, { purpose: "Why", items: saved.items }), true);
  assert.equal(sameContext(saved, { purpose: "Why", items: [] }), false);
  assert.equal(sameContext(saved, { purpose: "Different", items: saved.items }), false);
  // A rejected row alone is not an unsaved change.
  assert.equal(sameContext(saved, { purpose: "Why", items: [...saved.items, items[1]] }), true);
  assert.equal(contextBadge({ purpose: "", items: [] }), "Context");
  assert.equal(contextBadge({ purpose: "Why", items: [] }), "Context · Purpose");
  assert.equal(contextBadge(saved), "Context · 1");
});

test("the context block of a meeting parses defensively", () => {
  for (const odd of [null, undefined, "text", 3, true, [], {}, { items: "x" }, { items: [] }, { purpose: "   ", items: [null, 4, {}, { name: "" }] }]) {
    assert.equal(parseMeetingContext(odd), null, JSON.stringify(odd));
  }
  const parsed = parseMeetingContext({
    purpose: "  Decide the invoice export  ",
    items: [
      { name: "Brief.md", status: "ready", reason: null, chars: 1200, summary: "What the audit needs" },
      { name: "deck.pptx", status: "skipped", reason: "Too long to read", chars: -4, summary: "" },
      { name: "scan.pdf", status: "weird", chars: "9" },
      { name: "x.csv", status: "failed", reason: 12 },
      { status: "ready" },
    ],
  });
  assert.deepEqual(parsed, {
    purpose: "Decide the invoice export",
    items: [
      { name: "Brief.md", status: "ready", reason: null, chars: 1200, summary: "What the audit needs" },
      { name: "deck.pptx", status: "skipped", reason: "Too long to read", chars: null, summary: null },
      { name: "scan.pdf", status: "pending", reason: null, chars: null, summary: null },
      { name: "x.csv", status: "failed", reason: null, chars: null, summary: null },
    ],
  });
  assert.deepEqual(parseMeetingContext({ purpose: "Only a purpose" }), { purpose: "Only a purpose", items: [] });
});

test("get_meeting carries the context block, and a meeting without one has null", () => {
  const withContext = parseMeetingStatus({ meeting: { meeting_id: "M1", status: "ready", context: { purpose: "P", items: [] } } }, "M1");
  assert.deepEqual(withContext.context, { purpose: "P", items: [] });
  assert.equal(parseMeetingStatus({ meeting: { meeting_id: "M1", status: "ready" } }, "M1").context, null);
});

test("a file name longer than the service accepts is refused by characters, not UTF-16 units", () => {
  const long = `${"a".repeat(197)}.md`; // 200 characters
  assert.equal(classifyFile({ name: long, type: "", size: 10 }).ok, true);
  assert.deepEqual(classifyFile({ name: `b${long}`, type: "", size: 10 }), { ok: false, reason: REASON_NAME, code: "name" });
  const emoji = `${"😀".repeat(100)}.md`; // 103 characters, 203 UTF-16 units
  assert.equal(classifyFile({ name: emoji, type: "", size: 10 }).ok, true);
});
