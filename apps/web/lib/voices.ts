/**
 * Motivation vs Logic
 * Motivation: The diarizer sometimes cannot be told who a voice is, so "Speaker 3" stays in the
 * transcript. A person can only name that voice if they can hear it: a few clear stretches of it, not
 * a one-word interjection, spread across the recording.
 * Logic: Merge a voice's neighbouring lines into turns, score each turn by length and wordiness (a turn
 * with two voices at once scores low), then take the best three that are far apart in time. Pure
 * functions, so the choice can be tested without a browser.
 */
import { speakerName } from "@/lib/present";
import type { Span } from "@/lib/types";

export type Slice = {
  id: string;
  voiceId: string;
  startMs: number;
  endMs: number;
  text: string;
};

export type Candidate = { id: string; name: string };

const MERGE_GAP_MS = 1500;
const MIN_TURN_MS = 2500;
const MAX_CLIP_MS = 20_000;
const PAD_MS = 300;
const FAR_APART_MS = 45_000;
const NEAR_MS = 10_000;

type Turn = { voiceId: string; startMs: number; endMs: number; text: string; overlap: boolean; spanId: string };

/** Voices that have speech but no name from any source (typed, the picture, or what was said). */
export function unknownVoices(spans: Span[], names: Map<string, string>): string[] {
  const talk = new Map<string, number>();
  for (const span of spans) {
    if (span.kind !== "speech" || !span.speaker_hypothesis_id || span.start_ms === null || span.end_ms === null) continue;
    talk.set(span.speaker_hypothesis_id, (talk.get(span.speaker_hypothesis_id) ?? 0) + Math.max(0, span.end_ms - span.start_ms));
  }
  return [...talk.entries()]
    .filter(([id, ms]) => ms > 0 && !(names.get(id) ?? "").trim())
    .sort((left, right) => right[1] - left[1])
    .map(([id]) => id);
}

function turnsOf(spans: Span[], voiceId: string): Turn[] {
  const speech = spans
    .filter((span) => span.kind === "speech" && span.start_ms !== null && span.end_ms !== null && span.text.trim())
    .sort((left, right) => (left.start_ms ?? 0) - (right.start_ms ?? 0));
  const turns: Turn[] = [];
  let current: Turn | null = null;
  for (const span of speech) {
    const start = span.start_ms as number;
    const end = span.end_ms as number;
    if (span.speaker_hypothesis_id !== voiceId) {
      if (current) turns.push(current);
      current = null;
      continue;
    }
    if (current && start - current.endMs <= MERGE_GAP_MS) {
      current.endMs = Math.max(current.endMs, end);
      current.text = `${current.text} ${span.text.trim()}`;
      current.overlap = current.overlap || span.overlap;
    } else {
      if (current) turns.push(current);
      current = { voiceId, startMs: start, endMs: end, text: span.text.trim(), overlap: span.overlap, spanId: span.id };
    }
  }
  if (current) turns.push(current);
  return turns;
}

function score(turn: Turn): number {
  const seconds = Math.min(turn.endMs - turn.startMs, 15_000) / 15_000;
  const words = Math.min(turn.text.split(/\s+/).filter(Boolean).length, 40) / 40;
  return 0.5 * seconds + 0.4 * words - (turn.overlap ? 0.5 : 0);
}

/** The best `count` slices of a voice for a person to listen to, far apart in time when the recording allows. */
export function topSlices(spans: Span[], voiceId: string, count = 3): Slice[] {
  const turns = turnsOf(spans, voiceId);
  const long = turns.filter((turn) => turn.endMs - turn.startMs >= MIN_TURN_MS);
  const pool = (long.length >= count ? long : turns).slice().sort((left, right) => score(right) - score(left));
  const chosen: Turn[] = [];
  for (const gap of [FAR_APART_MS, NEAR_MS, 0]) {
    for (const turn of pool) {
      if (chosen.length >= count) break;
      if (chosen.includes(turn)) continue;
      if (chosen.every((other) => Math.abs(other.startMs - turn.startMs) >= gap)) chosen.push(turn);
    }
  }
  return chosen
    .sort((left, right) => left.startMs - right.startMs)
    .map((turn) => {
      const startMs = Math.max(0, turn.startMs - PAD_MS);
      return {
        id: turn.spanId,
        voiceId,
        startMs,
        endMs: Math.min(turn.endMs + PAD_MS, startMs + MAX_CLIP_MS),
        text: turn.text,
      };
    });
}

/** People already detected that this voice could be registered as: every named voice but itself, one per name. */
export function registerTargets(names: Map<string, string>, voiceId: string): Candidate[] {
  const seen = new Set<string>();
  const out: Candidate[] = [];
  for (const [id, name] of names) {
    const key = name.trim().toLowerCase();
    if (id === voiceId || !key || seen.has(key)) continue;
    seen.add(key);
    out.push({ id, name: name.trim() });
  }
  return out.sort((left, right) => left.name.localeCompare(right.name));
}

export type TalkTimeRow = {
  id: string;
  voiceIds: string[];
  name: string;
  share: number;
};

const PHONETIC_ALIASES: [string, string][] = [
  ["lee", "ly"], ["lee", "li"], ["ly", "li"],
  ["dan", "daniel"], ["bill", "william"], ["bob", "robert"],
  ["jim", "james"], ["mike", "michael"], ["dave", "david"],
  ["matt", "matthew"], ["chris", "christopher"], ["steve", "stephen"],
  ["steve", "steven"], ["jon", "john"], ["tom", "thomas"],
];

function samePerson(a: string, b: string): boolean {
  const normA = a.trim().toLowerCase();
  const normB = b.trim().toLowerCase();
  if (normA === normB) return true;
  if (normA.startsWith("speaker ") || normB.startsWith("speaker ")) return false;
  const tokA = normA.split(/\s+/);
  const tokB = normB.split(/\s+/);
  const [short, long_] = tokA.length <= tokB.length ? [tokA, tokB] : [tokB, tokA];
  if (long_.slice(0, short.length).join(" ") === short.join(" ")) return true;
  if (short.length === 1) {
    if (short[0] === long_[0]) return true;
    if (PHONETIC_ALIASES.some(([x, y]) => (short[0] === x && long_[0] === y) || (short[0] === y && long_[0] === x))) return true;
  }
  return false;
}

function longerName(a: string, b: string): string {
  const tokA = a.trim().split(/\s+/).length;
  const tokB = b.trim().split(/\s+/).length;
  if (tokA !== tokB) return tokA > tokB ? a : b;
  return a.length >= b.length ? a : b;
}

/**
 * Total speaking share per person.
 * Unifies fragmented or duplicate voice IDs sharing the same canonical display name or alias
 * into a single row, preventing isolated duplicate bars.
 */
export function talkTime(spans: Span[], names: Map<string, string>): TalkTimeRow[] {
  const totals = new Map<string, number>();
  for (const span of spans) {
    if (span.kind !== "speech" || !span.speaker_hypothesis_id || span.start_ms === null || span.end_ms === null) continue;
    totals.set(span.speaker_hypothesis_id, (totals.get(span.speaker_hypothesis_id) ?? 0) + Math.max(0, span.end_ms - span.start_ms));
  }
  const sum = [...totals.values()].reduce((left, right) => left + right, 0);
  if (sum <= 0) return [];

  // Group by canonical person identity (unifying split voice IDs or alias names)
  const clusters: { primaryId: string; voiceIds: string[]; name: string; ms: number }[] = [];
  for (const [id, ms] of totals.entries()) {
    const rawName = names.get(id) ?? speakerName(null, id);
    let match = clusters.find((c) => samePerson(c.name, rawName));
    if (!match) {
      clusters.push({ primaryId: id, voiceIds: [id], name: rawName, ms });
    } else {
      match.voiceIds.push(id);
      match.ms += ms;
      match.name = longerName(match.name, rawName);
      if (ms > (totals.get(match.primaryId) ?? 0)) {
        match.primaryId = id;
      }
    }
  }

  return clusters
    .map((entry) => ({ id: entry.primaryId, voiceIds: entry.voiceIds, name: entry.name, share: entry.ms / sum }))
    .sort((left, right) => right.share - left.share);
}
