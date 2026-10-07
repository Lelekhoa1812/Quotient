/**
 * Motivation vs Logic
 * Motivation: Owners, clocks, and quote highlights are projections of span
 * fields. The portal must not invent a name or a time the graph did not store.
 * Logic: A null owner_span_id renders the fixed phrase. Quote highlighting
 * slices text only when the slice equals the stored quote. Clocks divide
 * start_ms by 1000 for the media element.
 */

import type { ActionItem, Citation, Span } from "@/lib/types";

export function formatMs(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const padded = String(seconds).padStart(2, "0");
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, "0")}:${padded}`;
  return `${minutes}:${padded}`;
}

export function formatTableNumber(value: number): string {
  return JSON.stringify(value);
}

export function ownerText(action: ActionItem, spans: Span[]): string {
  if (!action.owner_span_id) return "not stated";
  const span = spans.find((item) => item.id === action.owner_span_id);
  const text = span?.text.trim() ?? "";
  return text.length > 0 ? text : "not stated";
}

export function isProposed(action: ActionItem): boolean {
  return action.acceptance !== "accepted";
}

export function speakerText(span: Span): string {
  if (span.speaker_label && span.speaker_label.trim().length > 0) return span.speaker_label;
  if (span.speaker_hypothesis_id) return span.speaker_hypothesis_id;
  return "Speaker not named";
}

export function quoteParts(
  text: string,
  citation: Citation | null,
): { before: string; quote: string; after: string } | null {
  if (!citation || citation.char_start === null || citation.char_end === null) return null;
  const start = citation.char_start;
  const end = citation.char_end;
  if (start < 0 || end > text.length || start >= end) return null;
  const quote = text.slice(start, end);
  if (citation.quote && quote !== citation.quote) return null;
  return { before: text.slice(0, start), quote, after: text.slice(end) };
}

export function dueText(action: ActionItem): string | null {
  if (action.due_kind === "none" || !action.due_surface) return null;
  return action.due_surface;
}

/**
 * Motivation vs Logic
 * Motivation: Protocol statuses and artifact keys are stored for the worker.
 * Business users need the same states in ordinary words.
 * Logic: Map the closed status and artifact sets. Any unknown key is shown
 * with underscores turned into spaces, capitalized once.
 */
const STATUS_LABEL: Record<string, string> = {
  queued: "Queued",
  working: "Working",
  ready: "Ready",
  needs_review: "Needs review",
  failed: "Could not finish",
  cancelled: "Cancelled",
  completed: "Finished",
  input_required: "Needs a file",
  pending: "Queued",
  incomplete: "Incomplete",
  unresolved: "Unresolved",
  contradicted: "Contradicted",
  numeric_failed: "Numbers to check",
  supported: "Supported",
  supports: "Supports",
  conflicts: "Conflicts",
  unknown: "Not settled",
};

const ARTIFACT_LABEL: Record<string, string> = {
  ledger: "Record",
  claims: "Claims",
  counterevidence: "Opposing points",
  entailment: "Support",
  coverage: "Coverage",
  exports: "Downloads",
};

function humanize(value: string): string {
  const words = value.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function statusLabel(status: string): string {
  const key = status.trim();
  if (!key) return "";
  return STATUS_LABEL[key] ?? humanize(key);
}

export function statusTone(status: string): "ready" | "review" | "working" | "quiet" {
  if (status === "ready" || status === "completed") return "ready";
  if (status === "needs_review") return "review";
  if (status === "failed" || status === "cancelled") return "quiet";
  return "working";
}

export function artifactLabel(name: string): string {
  return ARTIFACT_LABEL[name] ?? humanize(name);
}

export function meetingTitle(title: string, filename: string, meetingId: string | null): string {
  const name = title.trim();
  const file = filename.trim();
  if (name && name !== meetingId) return name;
  if (file) return file;
  return "Meeting";
}

export function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" }).format(date);
}

/**
 * Motivation vs Logic
 * Motivation: The catalog date is a calendar day. The row also has to show
 * the clock time the meeting was created, in a fixed HH:MM shape.
 * Logic: Read the local hour and minute from the stored instant and zero-pad
 * both. An unparseable instant renders nothing.
 */
export function formatClock(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
}

export function reviewLine(count: number | null): string {
  if (count === null || count <= 0) return "";
  return count === 1 ? "1 item to review" : `${count} items to review`;
}
