/**
 * Motivation vs Logic
 * Motivation: A recording alone does not say what the meeting was for, what the product is
 * called or who the people are. A person can hand the analysis that reference (slides, a brief,
 * a glossary, pasted notes) and the agents must treat it as source-of-truth reference, never as
 * something said in the meeting. Everything that decides what may be added, how big it may be
 * and what is sent to the service is a plain function here so it can be tested without a browser.
 * Logic: One accepted-type table drives classification, the icon and the media type sent. A
 * rejected file stays in the list with its reason instead of vanishing. Limits (25 MB a file,
 * 20 items, 100 MB in total) stop further additions with a plain sentence. Pasted notes become
 * Markdown files named "Pasted note N.md". The prepare_context request and result are shaped
 * and read here; the network calls live in lib/mcp/client.ts.
 */

import { unwrapTool } from "@/lib/graph";
import { asArray, asFinite, asRecord, asString } from "@/lib/json";

export const MAX_FILE_BYTES = 25 * 1024 * 1024;
export const MAX_ITEMS = 20;
export const MAX_TOTAL_BYTES = 100 * 1024 * 1024;
export const MAX_PURPOSE_CHARS = 2000;
export const MAX_NOTE_CHARS = 200_000;
export const UPLOAD_CONCURRENCY = 2;

export type ContextKind = "document" | "table" | "slides" | "code" | "note";
export type ContextStatus = "ready" | "uploading" | "failed" | "rejected";

export type ContextItem = {
  id: string;
  kind: ContextKind;
  /** File name, or the title of a pasted note (without ".md"). */
  name: string;
  mediaType: string;
  /** Bytes. For a note, the UTF-8 size of its text. */
  size: number;
  /** Characters, for a note; null for a file. */
  chars: number | null;
  file: File | null;
  text: string | null;
  status: ContextStatus;
  /** 0 to 1 while uploading. */
  progress: number;
  /** A plain sentence for a rejected or failed item. */
  reason: string;
};

export type ContextState = { purpose: string; items: ContextItem[] };

export const EMPTY_CONTEXT: ContextState = { purpose: "", items: [] };

type Accepted = { kind: ContextKind; mediaType: string; label: string };

/** Every extension the analysis can read as reference. No images, recordings or archives. */
export const ACCEPTED_TYPES: Record<string, Accepted> = {
  pdf: { kind: "document", mediaType: "application/pdf", label: "PDF" },
  docx: { kind: "document", mediaType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", label: "Word" },
  pptx: { kind: "slides", mediaType: "application/vnd.openxmlformats-officedocument.presentationml.presentation", label: "PowerPoint" },
  xlsx: { kind: "table", mediaType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", label: "Excel" },
  xls: { kind: "table", mediaType: "application/vnd.ms-excel", label: "Excel" },
  csv: { kind: "table", mediaType: "text/csv", label: "CSV" },
  json: { kind: "code", mediaType: "application/json", label: "JSON" },
  xml: { kind: "code", mediaType: "application/xml", label: "XML" },
  html: { kind: "document", mediaType: "text/html", label: "HTML" },
  htm: { kind: "document", mediaType: "text/html", label: "HTML" },
  md: { kind: "document", mediaType: "text/markdown", label: "Markdown" },
  markdown: { kind: "document", mediaType: "text/markdown", label: "Markdown" },
  txt: { kind: "document", mediaType: "text/plain", label: "Text" },
  epub: { kind: "document", mediaType: "application/epub+zip", label: "EPUB" },
};

/** The value for an <input accept>: every accepted extension. */
export const ACCEPT_ATTRIBUTE = Object.keys(ACCEPTED_TYPES).map((ext) => `.${ext}`).join(",");

// Used only when a file has no known extension, so a browser-reported type still gets it in.
const MIME_TYPES: Record<string, string> = {
  "application/pdf": "pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
  "application/vnd.ms-excel": "xls",
  "text/csv": "csv",
  "application/json": "json",
  "application/xml": "xml",
  "text/xml": "xml",
  "text/html": "html",
  "text/markdown": "md",
  "text/plain": "txt",
  "application/epub+zip": "epub",
};

const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "tif", "tiff", "heic", "heif", "avif", "ico"]);
const RECORDING_EXTENSIONS = new Set([
  "mp4", "m4v", "mov", "webm", "mkv", "avi", "wmv", "mpg", "mpeg", "3gp",
  "mp3", "m4a", "aac", "wav", "flac", "ogg", "opus", "wma", "aiff", "amr",
]);

export const REASON_IMAGE = "Images aren't supported yet";
export const REASON_TYPE = "This type of file isn't supported";
export const REASON_SIZE = "Larger than 25 MB";
export const REASON_NAME = "The file name is longer than 200 characters. Rename it and add it again.";
export const REASON_EMPTY = "This file is empty";

export type FileLike = { name: string; type?: string; size: number };

export type Classification =
  | { ok: true; kind: ContextKind; mediaType: string }
  | { ok: false; reason: string; code: "image" | "type" | "size" | "empty" | "name" };

/** https, or plain http only to this machine (local object storage). */
function isSafeUrl(url: string): boolean {
  if (url.startsWith("https://")) return true;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
  } catch {
    return false;
  }
}

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 && dot < name.length - 1 ? name.slice(dot + 1).toLowerCase() : "";
}

/** Decide whether a file can be reference, and if not, say why in one plain sentence. */
export function classifyFile(file: FileLike): Classification {
  const extension = extensionOf(file.name);
  const type = (file.type ?? "").toLowerCase().split(";")[0].trim();
  // Only the extension decides: the service accepts files by their extension, and browsers report odd types
  // for csv, md and old Office files, so a type alone would let through a name the service then refuses.
  const accepted: Accepted | undefined = ACCEPTED_TYPES[extension];
  if (!accepted) {
    const image = type.startsWith("image/") || IMAGE_EXTENSIONS.has(extension);
    return image ? { ok: false, reason: REASON_IMAGE, code: "image" } : { ok: false, reason: REASON_TYPE, code: "type" };
  }
  if ([...file.name].length > 200) return { ok: false, reason: REASON_NAME, code: "name" }; // the service counts characters, not UTF-16 units
  if (file.size <= 0) return { ok: false, reason: REASON_EMPTY, code: "empty" };
  if (file.size > MAX_FILE_BYTES) return { ok: false, reason: REASON_SIZE, code: "size" };
  return { ok: true, kind: accepted.kind, mediaType: accepted.mediaType };
}

/** A recording belongs to the meeting itself; everything else is reference for the context list. */
export function isRecording(file: { name: string; type?: string }): boolean {
  const type = (file.type ?? "").toLowerCase();
  if (type.startsWith("audio/") || type.startsWith("video/")) return true;
  return RECORDING_EXTENSIONS.has(extensionOf(file.name));
}

export function splitRecordings(files: File[]): { recordings: File[]; others: File[] } {
  const recordings: File[] = [];
  const others: File[] = [];
  for (const file of files) (isRecording(file) ? recordings : others).push(file);
  return { recordings, others };
}

export function formatBytes(bytes: number): string {
  const size = Number.isFinite(bytes) && bytes > 0 ? bytes : 0;
  if (size < 1024) return `${Math.round(size)} B`;
  const units = ["KB", "MB", "GB"];
  let value = size / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const text = value >= 100 ? String(Math.round(value)) : value.toFixed(1).replace(/\.0$/, "");
  return `${text} ${units[unit]}`;
}

export function isActive(item: ContextItem): boolean {
  return item.status !== "rejected";
}

export function activeItems(items: ContextItem[]): ContextItem[] {
  return items.filter(isActive);
}

export function totals(items: ContextItem[]): { count: number; bytes: number } {
  const active = activeItems(items);
  return { count: active.length, bytes: active.reduce((sum, item) => sum + item.size, 0) };
}

/** "3 items · 4.2 MB", or an empty string when nothing counts. */
export function totalsLine(items: ContextItem[]): string {
  const { count, bytes } = totals(items);
  if (count === 0) return "";
  return `${count} ${count === 1 ? "item" : "items"} · ${formatBytes(bytes)}`;
}

let counter = 0;
function newId(): string {
  counter += 1;
  return `ctx-${Date.now().toString(36)}-${counter}`;
}

export type Addition = { items: ContextItem[]; notice: string };

/**
 * Turn picked or dropped files into rows. A rejected file becomes a row with its reason, and
 * counts against nothing. Accepted files stop being added at the item or total-size limit.
 */
export function planAdditions(existing: ContextItem[], incoming: FileLike[]): Addition {
  const added: ContextItem[] = [];
  let count = totals(existing).count;
  let bytes = totals(existing).bytes;
  let duplicates = 0;
  let left = 0;
  let stopped: "items" | "bytes" | null = null;
  const seen = new Set(activeItems(existing).filter((item) => item.file).map((item) => `${item.name}:${item.size}`));
  for (let index = 0; index < incoming.length; index += 1) {
    const file = incoming[index];
    const verdict = classifyFile(file);
    if (!verdict.ok) {
      added.push(row({ name: file.name, kind: "document", mediaType: file.type ?? "", size: file.size, file: null, status: "rejected", reason: verdict.reason }));
      continue;
    }
    if (seen.has(`${file.name}:${file.size}`)) {
      duplicates += 1;
      continue;
    }
    if (count >= MAX_ITEMS) stopped = "items";
    else if (bytes + file.size > MAX_TOTAL_BYTES) stopped = "bytes";
    if (stopped) {
      left = incoming.slice(index).filter((rest) => classifyFile(rest).ok).length;
      break;
    }
    seen.add(`${file.name}:${file.size}`);
    count += 1;
    bytes += file.size;
    added.push(row({ name: file.name, kind: verdict.kind, mediaType: verdict.mediaType, size: file.size, file: file as File, status: "ready" }));
  }
  const parts: string[] = [];
  if (stopped === "items") parts.push(`You can add up to ${MAX_ITEMS} items.`);
  if (stopped === "bytes") parts.push(`That would go over ${formatBytes(MAX_TOTAL_BYTES)} in total.`);
  if (stopped && left > 0) parts.push(`${left} ${left === 1 ? "file was" : "files were"} not added.`);
  if (duplicates > 0) parts.push(`${duplicates} ${duplicates === 1 ? "file was" : "files were"} already added.`);
  return { items: added, notice: parts.join(" ") };
}

function row(fields: Pick<ContextItem, "name" | "kind" | "mediaType" | "size" | "file" | "status"> & { reason?: string }): ContextItem {
  return { id: newId(), chars: null, text: null, progress: 0, reason: "", ...fields };
}

/** A title safe to use as a file name: no path characters, no control characters, no trailing ".md". */
export function cleanNoteTitle(raw: string): string {
  return raw
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/[\\/:*?"<>|]/g, "-")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\.md$/i, "")
    .trim()
    .slice(0, 80)
    .trim();
}

/** "Pasted note 1", then 2, and so on: the lowest number not already used. */
export function defaultNoteTitle(existing: ContextItem[]): string {
  const used = new Set(existing.map((item) => item.name.toLowerCase()));
  for (let number = 1; number < 1000; number += 1) {
    const title = `Pasted note ${number}`;
    if (!used.has(title.toLowerCase())) return title;
  }
  return `Pasted note ${existing.length + 1}`;
}

/** Make a title unique among the names already in the list by adding " 2", " 3". */
function uniqueTitle(title: string, existing: ContextItem[]): string {
  const used = new Set(activeItems(existing).map((item) => item.name.toLowerCase()));
  if (!used.has(title.toLowerCase())) return title;
  for (let number = 2; number < 1000; number += 1) {
    const candidate = `${title} ${number}`;
    if (!used.has(candidate.toLowerCase())) return candidate;
  }
  return `${title} ${existing.length + 1}`;
}

export function noteFileName(title: string): string {
  return `${title}.md`;
}

export function noteToFile(title: string, text: string): File {
  return new File([text], noteFileName(title), { type: "text/markdown" });
}

export function byteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

export type NoteResult = { item: ContextItem | null; notice: string };

/** Add pasted text as a note. Empty text is not addable; limits apply as for files. */
export function planNote(existing: ContextItem[], rawTitle: string, text: string): NoteResult {
  if (text.trim().length === 0) return { item: null, notice: "Add some text first." };
  if (text.length > MAX_NOTE_CHARS) return { item: null, notice: `A note can be up to ${MAX_NOTE_CHARS.toLocaleString("en-AU")} characters.` };
  const current = totals(existing);
  if (current.count >= MAX_ITEMS) return { item: null, notice: `You can add up to ${MAX_ITEMS} items.` };
  const size = byteLength(text);
  if (current.bytes + size > MAX_TOTAL_BYTES) return { item: null, notice: `That would go over ${formatBytes(MAX_TOTAL_BYTES)} in total.` };
  const typed = cleanNoteTitle(rawTitle);
  const title = uniqueTitle(typed || defaultNoteTitle(existing), existing);
  const item = row({ name: title, kind: "note", mediaType: "text/markdown", size, file: null, status: "ready" });
  item.text = text;
  item.chars = text.length;
  return { item, notice: `Added ${title}.` };
}

/** The same note after its text is edited in the list. */
export function withNoteText(item: ContextItem, text: string): ContextItem {
  const next = text.slice(0, MAX_NOTE_CHARS);
  return { ...item, text: next, chars: next.length, size: byteLength(next) };
}

export type UploadSpec = { id: string; file: File; mediaType: string };

/** What is sent for each active item: the File itself, or a Markdown file made from a note. */
export function toUploads(items: ContextItem[]): UploadSpec[] {
  const uploads: UploadSpec[] = [];
  for (const item of activeItems(items)) {
    if (item.file) uploads.push({ id: item.id, file: item.file, mediaType: item.mediaType });
    else if (item.text !== null) uploads.push({ id: item.id, file: noteToFile(item.name, item.text), mediaType: "text/markdown" });
  }
  return uploads;
}

export type PrepareArgs = { files: { filename: string; media_type: string; byte_size: number }[] };

/** The arguments of the prepare_context tool: one entry per file, 1 to 20, in order. */
export function buildPrepareArgs(uploads: UploadSpec[]): PrepareArgs {
  if (uploads.length < 1 || uploads.length > MAX_ITEMS) {
    throw new RangeError(`prepare_context takes 1 to ${MAX_ITEMS} files`);
  }
  return {
    files: uploads.map((upload) => ({
      filename: upload.file.name,
      media_type: upload.mediaType,
      byte_size: upload.file.size,
    })),
  };
}

export type UploadTarget = { url: string; headers: Record<string, string>; objectKey: string | null };

export type PrepareOutcome =
  | { ok: true; batchId: string; uploads: (UploadTarget | null)[] }
  | { ok: false; error: string };

const PREPARE_FAILED = "The context could not be prepared. Try again, or remove the context to start without it.";

/** The plain message of an MCP tool error result, or null when the result is not an error. */
export function toolErrorMessage(result: unknown): string | null {
  const record = asRecord(result);
  if (!record) return null;
  const body = asRecord(unwrapTool(result));
  const named = asString(body?.error);
  if (named && named.trim()) return named.trim();
  if (record.isError === true) {
    for (const block of asArray(record.content)) {
      const text = asString(asRecord(block)?.text);
      if (text && text.trim()) return text.trim();
    }
    return PREPARE_FAILED;
  }
  return null;
}

/** Read the prepare_context result: a batch and one upload target per requested file, or an error. */
export function parsePrepareResult(result: unknown, expected: number): PrepareOutcome {
  const failure = toolErrorMessage(result);
  if (failure) return { ok: false, error: failure };
  const body = asRecord(unwrapTool(result));
  const batchId = asString(body?.batch_id);
  if (!body || !batchId) return { ok: false, error: PREPARE_FAILED };
  const uploads: (UploadTarget | null)[] = Array.from({ length: expected }, () => null);
  const listed = asArray(body.uploads);
  listed.forEach((entry, position) => {
    const record = asRecord(entry);
    if (!record) return;
    const declared = asFinite(record.index);
    const index = declared !== null && Number.isInteger(declared) ? declared : position;
    const url = asString(record.upload_url);
    const method = (asString(record.method) ?? "PUT").toUpperCase();
    if (index < 0 || index >= expected || !url || !isSafeUrl(url) || method !== "PUT") return;
    const headers: Record<string, string> = {};
    for (const [key, value] of Object.entries(asRecord(record.headers) ?? {})) {
      if (typeof value === "string") headers[key] = value;
    }
    uploads[index] = { url, headers, objectKey: asString(record.object_key) };
  });
  return { ok: true, batchId, uploads };
}

/** Run a worker over items, at most `limit` at a time. A worker must not throw. */
export async function runPool<T>(items: T[], limit: number, worker: (item: T, index: number) => Promise<void>): Promise<void> {
  let next = 0;
  const lanes = Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, async () => {
    while (next < items.length) {
      const index = next;
      next += 1;
      await worker(items[index], index);
    }
  });
  await Promise.all(lanes);
}

/** One plain sentence naming what the meeting started without. */
export function skippedNotice(names: string[]): string {
  if (names.length === 0) return "";
  if (names.length === 1) return `The meeting started without ${names[0]}, which couldn't be uploaded.`;
  return `The meeting started without ${names.length} context items that couldn't be uploaded: ${names.join(", ")}.`;
}

/** Whether two states would save the same thing; rejected rows are never saved, so they do not count. */
export function sameContext(left: ContextState, right: ContextState): boolean {
  if (left.purpose.trim() !== right.purpose.trim()) return false;
  const a = activeItems(left.items);
  const b = activeItems(right.items);
  if (a.length !== b.length) return false;
  return a.every((item, index) => item.id === b[index].id && item.text === b[index].text && item.name === b[index].name);
}

/** What gets kept when the person saves: no rejected rows, every item ready. */
export function cleanForSave(state: ContextState): ContextState {
  return {
    purpose: state.purpose.trim(),
    items: activeItems(state.items).map((item) => ({ ...item, status: "ready", progress: 0, reason: "" })),
  };
}

export function hasContext(state: ContextState): boolean {
  return state.items.length > 0 || state.purpose.trim().length > 0;
}

/** The label on the "+ Context" button. */
export function contextBadge(state: ContextState): string {
  const { count } = totals(state.items);
  if (count > 0) return `Context · ${count}`;
  return state.purpose.trim() ? "Context · Purpose" : "Context";
}
