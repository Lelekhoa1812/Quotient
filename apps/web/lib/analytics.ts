/**
 * Motivation vs Logic
 * Motivation: The Insights page must show what the recording was like (who carried it, when it was
 * busy, how topics split the time, how evidence and open items built up) without a single number
 * a reader cannot recompute. Charts that decorate were the old noise; these answer questions.
 * Logic: Everything here is derived from the spans, claims and digest already on the graph page.
 * Time is shared out to buckets by overlap, never smoothed or interpolated. Voices are keyed by
 * their hypothesis id and named through the same name map the rest of the page uses, so a name a
 * person typed appears in every chart. A series with no data returns empty and the page hides it.
 */
import type { Digest } from "@/lib/digest";
import type { Claim, Span } from "@/lib/types";

export type Voice = { id: string; name: string; ms: number; share: number; words: number; turns: number; longestMs: number; wpm: number };

const WORDS = /[\p{L}\p{N}][\p{L}\p{N}'’-]*/gu;

export function isSpeech(span: Span): boolean {
  return span.kind === "speech" && span.start_ms !== null && span.end_ms !== null && span.end_ms > span.start_ms && (span.text || span.raw_text).trim().length > 0;
}

export function wordCount(text: string): number {
  return text.match(WORDS)?.length ?? 0;
}

function speechSpans(spans: Span[]): Span[] {
  return spans.filter(isSpeech).sort((left, right) => (left.start_ms ?? 0) - (right.start_ms ?? 0));
}

/** One entry per voice, loudest first. Spans with no voice id are not charted. */
export function voiceStats(spans: Span[], names: Map<string, string>): Voice[] {
  const rows = new Map<string, Voice>();
  const reach = new Map<string, number>(); // end of the speech already counted for each voice
  let previous: string | null = null;
  let turnStart = 0;
  let turnEnd = 0;
  const closeTurn = (id: string | null) => {
    if (!id) return;
    const row = rows.get(id);
    if (row) row.longestMs = Math.max(row.longestMs, turnEnd - turnStart);
  };
  for (const span of speechSpans(spans)) {
    const id = span.speaker_hypothesis_id;
    if (!id) continue;
    const row = rows.get(id) ?? { id, name: names.get(id) ?? fallbackName(id), ms: 0, share: 0, words: 0, turns: 0, longestMs: 0, wpm: 0 };
    rows.set(id, row);
    // Overlapping lines of one voice are counted once.
    const from = Math.max(span.start_ms ?? 0, reach.get(id) ?? 0);
    if ((span.end_ms ?? 0) > from) row.ms += (span.end_ms ?? 0) - from;
    reach.set(id, Math.max(reach.get(id) ?? 0, span.end_ms ?? 0));
    row.words += wordCount(span.text || span.raw_text);
    if (previous !== id || (span.start_ms ?? 0) - turnEnd > 4000) {
      closeTurn(previous);
      row.turns += 1;
      turnStart = span.start_ms ?? 0;
    }
    turnEnd = span.end_ms ?? 0;
    previous = id;
  }
  closeTurn(previous);
  const total = [...rows.values()].reduce((sum, row) => sum + row.ms, 0);
  for (const row of rows.values()) {
    row.share = total > 0 ? row.ms / total : 0;
    row.wpm = row.ms > 0 ? Math.round((row.words / row.ms) * 60_000) : 0;
  }
  return [...rows.values()].sort((left, right) => right.ms - left.ms);
}

function fallbackName(id: string): string {
  const index = Number(id.match(/(\d+)\s*$/)?.[1]);
  return Number.isFinite(index) ? `Speaker ${index + 1}` : "Unnamed speaker";
}

export type Bucket = { startMs: number; endMs: number; ms: number; words: number; byVoice: Record<string, number> };

/** Talk time and words per bucket; a span crossing a boundary is shared out by overlap. */
export function buckets(spans: Span[], bucketMs: number, durationMs: number): Bucket[] {
  if (!(bucketMs > 0) || !(durationMs > 0)) return [];
  const count = Math.max(1, Math.ceil(durationMs / bucketMs));
  const out: Bucket[] = Array.from({ length: count }, (_, index) => ({ startMs: index * bucketMs, endMs: Math.min(durationMs, (index + 1) * bucketMs), ms: 0, words: 0, byVoice: {} }));
  for (const span of speechSpans(spans)) {
    const start = span.start_ms ?? 0;
    const end = span.end_ms ?? 0;
    const words = wordCount(span.text || span.raw_text);
    const length = end - start;
    for (let index = Math.floor(start / bucketMs); index <= Math.min(count - 1, Math.floor((end - 1) / bucketMs)); index += 1) {
      const overlap = Math.min(end, (index + 1) * bucketMs) - Math.max(start, index * bucketMs);
      if (overlap <= 0) continue;
      const bucket = out[index];
      bucket.ms += overlap;
      bucket.words += (words * overlap) / length;
      const id = span.speaker_hypothesis_id;
      if (id) bucket.byVoice[id] = (bucket.byVoice[id] ?? 0) + overlap;
    }
  }
  return out;
}

/** A readable bucket width: about 20-48 columns, never finer than 15 s. */
export function bucketWidth(durationMs: number): number {
  const steps = [15_000, 30_000, 60_000, 120_000, 300_000, 600_000];
  return steps.find((step) => durationMs / step <= 48) ?? 600_000;
}

export type TopicMix = { title: string; startMs: number; endMs: number; ms: number; byVoice: Record<string, number> };

export function topicMix(chapters: Digest["chapters"], spans: Span[]): TopicMix[] {
  const speech = speechSpans(spans);
  return chapters.map((chapter) => {
    const byVoice: Record<string, number> = {};
    for (const span of speech) {
      const overlap = Math.min(span.end_ms ?? 0, chapter.endMs) - Math.max(span.start_ms ?? 0, chapter.startMs);
      if (overlap > 0 && span.speaker_hypothesis_id) byVoice[span.speaker_hypothesis_id] = (byVoice[span.speaker_hypothesis_id] ?? 0) + overlap;
    }
    return { title: chapter.title, startMs: chapter.startMs, endMs: chapter.endMs, ms: Math.max(0, chapter.endMs - chapter.startMs), byVoice };
  });
}

/** Who spoke right after whom. Counts hand-offs between different voices; long silences break the chain. */
export function handoffs(spans: Span[]): { from: string; to: string; count: number }[] {
  const counts = new Map<string, number>();
  let last: { id: string; end: number } | null = null;
  for (const span of speechSpans(spans)) {
    const id = span.speaker_hypothesis_id;
    if (!id) continue;
    const start = span.start_ms ?? 0;
    if (last && last.id !== id && start - last.end <= 15_000) {
      const key = `${last.id}\u0000${id}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    last = { id, end: span.end_ms ?? start };
  }
  return [...counts.entries()].map(([key, count]) => {
    const [from, to] = key.split("\u0000");
    return { from, to, count };
  });
}

export type EvidenceKey = "confirmed" | "likely" | "unchecked" | "contradicted";
export const EVIDENCE_LABEL: Record<EvidenceKey, string> = {
  confirmed: "Confirmed",
  likely: "Likely",
  unchecked: "Not confirmed",
  contradicted: "Contradicted",
};

function normalized(text: string): string {
  return text.normalize("NFKC").toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

function evidenceOf(claim: Claim): EvidenceKey {
  if (claim.confidence === "confirmed" || claim.confidence === "likely" || claim.confidence === "contradicted") return claim.confidence;
  return "unchecked";
}

const RANK: Record<EvidenceKey, number> = { contradicted: 3, unchecked: 2, likely: 1, confirmed: 0 };

/** Distinct statements, each with the weakest tier it was given, so repeated extraction does not inflate counts. */
export function distinctClaims(claims: Claim[]): { claim: Claim; tier: EvidenceKey }[] {
  const seen = new Map<string, { claim: Claim; tier: EvidenceKey }>();
  for (const claim of claims) {
    const key = normalized(claim.text) || claim.id;
    const tier = evidenceOf(claim);
    const known = seen.get(key);
    if (!known || RANK[tier] > RANK[known.tier]) seen.set(key, { claim, tier });
  }
  return [...seen.values()];
}

export function evidenceMix(claims: Claim[]): Record<EvidenceKey, number> {
  const out: Record<EvidenceKey, number> = { confirmed: 0, likely: 0, unchecked: 0, contradicted: 0 };
  for (const item of distinctClaims(claims)) out[item.tier] += 1;
  return out;
}

export function claimKinds(claims: Claim[]): { kind: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const item of distinctClaims(claims)) counts.set(item.claim.kind || "other", (counts.get(item.claim.kind || "other") ?? 0) + 1);
  return [...counts.entries()].map(([kind, count]) => ({ kind, count })).sort((left, right) => right.count - left.count);
}

function claimTime(claim: Claim): number | null {
  return claim.citations.find((item) => item.start_ms !== null)?.start_ms ?? null;
}

/** Statements per topic by evidence tier. A statement without a timed citation is not placed. */
export function evidenceByTopic(claims: Claim[], chapters: Digest["chapters"]): { title: string; startMs: number; counts: Record<EvidenceKey, number> }[] {
  const rows = chapters.map((chapter) => ({ title: chapter.title, startMs: chapter.startMs, endMs: chapter.endMs, counts: { confirmed: 0, likely: 0, unchecked: 0, contradicted: 0 } as Record<EvidenceKey, number> }));
  for (const { claim, tier } of distinctClaims(claims)) {
    const at = claimTime(claim);
    if (at === null) continue;
    const row = rows.find((item) => at >= item.startMs && at < item.endMs) ?? (at >= (rows[rows.length - 1]?.endMs ?? Infinity) ? rows[rows.length - 1] : undefined);
    if (row) row.counts[tier] += 1;
  }
  return rows.map(({ title, startMs, counts }) => ({ title, startMs, counts }));
}

export type MomentLane = { key: string; label: string; points: { startMs: number; text: string; tone: "plain" | "open" | "done" }[] };

/** What happened when: one lane per kind of outcome, only lanes that have points. */
export function momentLanes(digest: Digest): MomentLane[] {
  const lane = (key: string, label: string, points: MomentLane["points"]): MomentLane => ({ key, label, points: points.filter((point) => Number.isFinite(point.startMs)) });
  const at = (value: number | null) => value ?? Number.NaN;
  const lanes = [
    lane("decisions", "Decisions", digest.decisions.map((item) => ({ startMs: at(item.startMs), text: item.statement, tone: item.status === "agreed" ? "done" : "open" }))),
    lane("actions", "Actions", digest.actions.map((item) => ({ startMs: at(item.startMs), text: item.task, tone: item.agreed ? "done" : "open" }))),
    lane("questions", "Questions", digest.questions.map((item) => ({ startMs: at(item.startMs), text: item.question, tone: item.answered ? "done" : "open" }))),
    lane("disagreements", "Disagreements", digest.disagreements.map((item) => ({ startMs: at(item.startMs), text: item.topic, tone: "open" }))),
    lane("risks", "Risks", digest.risks.map((item) => ({ startMs: at(item.startMs), text: item.risk, tone: "plain" }))),
    lane("figures", "Figures", digest.figures.map((item) => ({ startMs: at(item.startMs), text: `${item.value} ${item.what}`, tone: "plain" }))),
  ];
  return lanes.filter((item) => item.points.length > 0);
}

export type Cumulative = { key: string; label: string; steps: { atMs: number; value: number }[] };

/** Running totals over the recording: how decisions, actions, questions and answers built up. */
export function cumulative(digest: Digest): Cumulative[] {
  const series = (key: string, label: string, times: (number | null)[]): Cumulative => {
    const sorted = times.filter((value): value is number => value !== null).sort((left, right) => left - right);
    return { key, label, steps: sorted.map((atMs, index) => ({ atMs, value: index + 1 })) };
  };
  const out = [
    series("questions", "Questions asked", digest.questions.map((item) => item.startMs)),
    // An answer with no recorded moment is not plotted: placing it at the question would fake a quick reply.
    series("answers", "Questions answered", digest.questions.filter((item) => item.answered).map((item) => item.answerMs)),
    series("decisions", "Decisions", digest.decisions.map((item) => item.startMs)),
    series("actions", "Actions", digest.actions.map((item) => item.startMs)),
  ];
  return out.filter((item) => item.steps.length > 0);
}

export type Kpi = { key: string; label: string; value: string; note?: string };

export function kpis(spans: Span[], digest: Digest | null, claims: Claim[], voices: Voice[]): Kpi[] {
  const speech = speechSpans(spans);
  const durationMs = Math.max(0, ...speech.map((span) => span.end_ms ?? 0));
  const talkMs = unionMs(speech);
  const words = speech.reduce((sum, span) => sum + wordCount(span.text || span.raw_text), 0);
  const out: Kpi[] = [];
  if (durationMs > 0) out.push({ key: "length", label: "Length", value: minutes(durationMs), note: talkMs > 0 ? `${Math.round((talkMs / durationMs) * 100)}% spoken` : undefined });
  if (voices.length > 0) out.push({ key: "voices", label: "Speakers", value: String(voices.length), note: voices[0] ? `${voices[0].name} led` : undefined });
  if (words > 0) out.push({ key: "words", label: "Words", value: new Intl.NumberFormat().format(words), note: talkMs > 0 ? `${Math.round((words / talkMs) * 60_000)} per minute` : undefined });
  if (digest) {
    const open = digest.questions.filter((item) => !item.answered).length;
    if (digest.questions.length) out.push({ key: "questions", label: "Questions", value: String(digest.questions.length), note: `${open} still open` });
  }
  return out;
}

/** Time with at least one voice speaking; overlapping spans are counted once. */
export function unionMs(spans: Span[]): number {
  let total = 0;
  let end = -Infinity;
  for (const span of spans) {
    const from = Math.max(span.start_ms ?? 0, end);
    const to = span.end_ms ?? 0;
    if (to > from) total += to - from;
    end = Math.max(end, to);
  }
  return total;
}

export function minutes(ms: number): string {
  const total = Math.round(ms / 1000);
  const hours = Math.floor(total / 3600);
  const mins = Math.floor((total % 3600) / 60);
  if (hours > 0) return `${hours} h ${mins} min`;
  return mins > 0 ? `${mins} min` : `${total} s`;
}
