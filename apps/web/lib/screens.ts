/**
 * Motivation vs Logic
 * Motivation: The video reader hands the portal each screen as raw text: the browser tab title, every navigation menu word, every row
 * of a table, "[unreadable]" fragments, the sign-in email and a layout paragraph. Printed as read, that is a wall of transcribed UI that
 * says nothing about what the presenter did or why it mattered.
 * Logic: Clean it in code, with no model, and keep only what a reader can use: a plain page title, the time range, a few label and value
 * highlights copied exactly from the screen (a figure shown as "Demo sample" says so), and the cleaned lines behind a disclosure. Repeated
 * readings of one page become one card; a screen with nothing readable is folded. Nothing here adds a word the screen did not show.
 */
import type { ScreenView } from "@/lib/types";

export type Highlight = { label: string; value: string; sample: boolean };

export type ScreenCard = {
  id: string;
  /** Every raw screen merged into this card. */
  ids: string[];
  kind: string;
  title: string;
  startMs: number;
  endMs: number;
  highlights: Highlight[];
  /** Cleaned lines, chrome and table bodies removed; behind the "Screen text" disclosure. */
  lines: string[];
  /** Table rows left out of `lines`. */
  moreRows: number;
  /** Nothing readable: shown as one quiet line, never as a card. */
  folded: boolean;
  /** The raw text and layout, exactly as read. */
  raw: string;
  layout: string;
  /** What this screen was for in the talk. Absent until a reading is joined on. */
  reading?: string | null;
  /** Set when the screen and the talk state different facts. */
  differs?: string | null;
};

const EMAIL = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/;
const URLISH = /(?:^|\s)(?:https?:\/\/|www\.)\S+|:\/\//i;
const ROW_ID = /^(?:#?[A-Z]{1,4}-?\d{3,}|[A-Z]{2,4}\d{4,})\b/;
const VALUE = /^[-+]?[$€£]?\d[\d,]*(?:\.\d+)?%?$/;
const SAMPLE = /\b(?:demo|sample)\b.*\b(?:sample|data)\b|\bdemo sample\b/i;
const CONTROLS = new Set(["cancel", "save", "continue", "search", "filter", "clear", "view", "manage", "allow", "loading..."]);

function norm(line: string): string {
  return line.toLowerCase().replace(/[^\p{L}\p{N}$%.]+/gu, " ").trim();
}

function wordCount(line: string): number {
  return line.trim().split(/\s+/).filter(Boolean).length;
}

/** Remove "[unreadable]" and the clipped word it leaves; null when nothing useful is left. */
function strip(line: string): string | null {
  const cleaned = line.replace(/\S*\[unreadable\]\S*/gi, "").replace(/\s{2,}/g, " ").trim();
  return cleaned.length >= 3 || /\d/.test(cleaned) ? cleaned : null; // "0%" and "13" are values, not debris
}

/** Lines that appear on many screens of one recording are the app's frame (menus, logo, environment banner), not the content. */
function chromeLines(screens: ScreenView[]): Set<string> {
  const counts = new Map<string, number>();
  for (const screen of screens) {
    const seen = new Set(screen.text.split("\n").map(norm).filter((line) => line && line.length <= 40));
    for (const line of seen) counts.set(line, (counts.get(line) ?? 0) + 1);
  }
  const floor = Math.max(3, Math.ceil(screens.length * 0.4));
  return new Set([...counts].filter(([, count]) => count >= floor).map(([line]) => line));
}

function isTabTitle(line: string, index: number): boolean {
  return index < 2 && line.includes(" | ") && !ROW_ID.test(line);
}

/** A run of four or more short words-only lines is a menu or a table header, not content. */
function dropMenuRuns(lines: string[]): string[] {
  const out: string[] = [];
  let run: string[] = [];
  const flush = () => {
    if (run.length < 4) out.push(...run);
    run = [];
  };
  for (const line of lines) {
    if (wordCount(line) <= 2 && !/\d/.test(line) && line.length <= 24) run.push(line);
    else {
      flush();
      out.push(line);
    }
  }
  flush();
  return out;
}

/** Keep what comes before a table's third row (filters, headings, the first two rows) and count the rest. */
function collapseRows(lines: string[]): { lines: string[]; more: number } {
  const starts = lines.flatMap((line, index) => (ROW_ID.test(line) ? [index] : []));
  if (starts.length < 4) return { lines, more: 0 };
  return { lines: lines.slice(0, starts[2]), more: starts.length - 2 };
}

function cleanLines(raw: string, chrome: Set<string>): string[] {
  const kept: string[] = [];
  const lines = raw.split("\n");
  for (let index = 0; index < lines.length; index += 1) {
    const original = lines[index].trim();
    if (!original || isTabTitle(original, index)) continue;
    const line = strip(original);
    if (!line || EMAIL.test(line) || URLISH.test(line) || CONTROLS.has(line.toLowerCase())) continue;
    if (/^last used$/i.test(line) && EMAIL.test(lines[index + 1] ?? "")) continue;
    if (chrome.has(norm(line))) continue;
    if (SAMPLE.test(line) || !kept.includes(line)) kept.push(line); // every "Demo sample" label stays: each figure carries its own
  }
  return dropMenuRuns(kept);
}

const DATE_LABEL = /\b(?:mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b|\d{1,2}[/-]\d{1,2}/i;

const KPI_LABEL = /\b(?:total|net|margin|cost|sales|amount|balance|profit|revenue|price|value|due|paid)\b/i;

/**
 * Label and value pairs. Before any table every pair counts; after the first table row only a pair whose label is a headline word does
 * (a record's totals), because a table's cells (a date, a run number, a price) are not figures a presenter points at.
 */
function highlights(lines: string[]): Highlight[] {
  const found: Highlight[] = [];
  const firstRow = lines.findIndex((line) => ROW_ID.test(line));
  const head = lines;
  for (let index = 1; index < head.length; index += 1) {
    const value = head[index];
    const looksLikeValue = VALUE.test(value) || (/^[-+]?[$€£]?\d/.test(value) && /[$%]/.test(value) && wordCount(value) <= 4);
    if (!looksLikeValue || ROW_ID.test(value)) continue;
    let labelIndex = index - 1;
    const sample = SAMPLE.test(head[labelIndex] ?? "");
    if (sample) labelIndex -= 1;
    const label = head[labelIndex];
    if (!label || VALUE.test(label) || wordCount(label) > 6 || ROW_ID.test(label) || label.endsWith(":") || label.includes(">") || /^\d/.test(label) || DATE_LABEL.test(label)) continue;
    if (firstRow >= 0 && index > firstRow && !KPI_LABEL.test(label)) continue;
    if (found.some((item) => item.label === label)) continue;
    found.push({ label, value, sample });
  }
  const money = (item: Highlight) => (/[$€£%]/.test(item.value) ? 0 : 1);
  return found.sort((left, right) => money(left) - money(right)).slice(0, 4);
}

function pickTitle(screen: ScreenView, lines: string[]): string {
  const given = screen.title.trim();
  if (given && !given.includes("[unreadable]") && !given.includes(" | ") && given.length <= 80) return given;
  const heading = lines.find((line) => !VALUE.test(line) && wordCount(line) <= 8 && !ROW_ID.test(line));
  return heading ?? "";
}

function tokens(lines: string[]): Set<string> {
  return new Set(lines.flatMap((line) => norm(line).split(" ")).filter((word) => word.length > 2));
}

function overlap(left: Set<string>, right: Set<string>): number {
  if (left.size === 0 || right.size === 0) return 0;
  let shared = 0;
  for (const word of left) if (right.has(word)) shared += 1;
  return shared / Math.min(left.size, right.size);
}

export function buildScreenCards(screens: ScreenView[]): ScreenCard[] {
  const ordered = [...screens].sort((left, right) => left.start_ms - right.start_ms);
  const chrome = chromeLines(ordered);
  const cards: ScreenCard[] = [];
  for (const screen of ordered) {
    const cleaned = cleanLines(screen.text, chrome);
    const collapsed = collapseRows(cleaned);
    const title = pickTitle(screen, collapsed.lines);
    const body = collapsed.lines.filter((line) => line !== title);
    const card: ScreenCard = {
      id: screen.id,
      ids: [screen.id],
      kind: screen.kind,
      title,
      startMs: screen.start_ms,
      endMs: screen.end_ms,
      highlights: highlights(cleaned),
      lines: body,
      moreRows: collapsed.more,
      folded: body.length < 2 && collapsed.lines.length < 2,
      raw: screen.text,
      layout: screen.details,
    };
    const previous = cards[cards.length - 1];
    const same =
      previous &&
      !previous.folded &&
      !card.folded &&
      card.startMs - previous.endMs <= 60_000 &&
      (norm(previous.title) === norm(card.title) || overlap(tokens(previous.lines), tokens(card.lines)) >= 0.8);
    if (same) {
      previous.ids.push(card.id);
      previous.endMs = Math.max(previous.endMs, card.endMs);
      // The fullest reading wins; a later reading with more content replaces the earlier one.
      if (card.lines.length + card.highlights.length > previous.lines.length + previous.highlights.length) {
        previous.lines = card.lines;
        previous.highlights = card.highlights;
        previous.moreRows = card.moreRows;
        previous.raw = card.raw;
        previous.layout = card.layout;
      }
    } else {
      cards.push(card);
    }
  }
  return cards;
}
