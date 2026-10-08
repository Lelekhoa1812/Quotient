/**
 * Motivation vs Logic
 * Motivation: Charts must answer a question a reader actually has, and every
 * number must be recomputable from stored evidence. Worker telemetry tables
 * (timeline density, per-span rows, an "unassigned" speaker bar) answer no such
 * question and are not charted.
 * Logic: Each insight is derived only from spans, claims, findings, actions and
 * speaker measures already on the graph page. A chart is returned only when its
 * data supports it: no bar for a single value, no speaker chart for one
 * unassigned speaker, no timeline without timed spans. Counts use distinct
 * statements so repeated extraction windows do not inflate totals. Nothing is
 * interpolated or smoothed.
 */
import { dimensionTitle } from "@/lib/present";
import { DIMENSIONS, type Claim, type Dimension, type Finding, type GraphPage, type Span } from "@/lib/types";

export type BarRow = { key: string; label: string; value: number; display: string; spanId?: string | null; startMs?: number | null };

export type Insight =
  | {
      kind: "bars";
      id: string;
      title: string;
      question: string;
      basis: string;
      rows: BarRow[];
      note?: string;
    }
  | {
      kind: "stack";
      id: string;
      title: string;
      question: string;
      basis: string;
      rows: { key: string; label: string; value: number; tone: "good" | "muted" | "warn" | "bad" }[];
    }
  | {
      kind: "columns";
      id: string;
      title: string;
      question: string;
      basis: string;
      unit: string;
      rows: BarRow[];
      note?: string;
    }
  | {
      kind: "moments";
      id: string;
      title: string;
      question: string;
      basis: string;
      durationMs: number;
      lanes: { key: string; label: string; points: { id: string; startMs: number; text: string; spanId: string | null }[] }[];
    };

// Only transcribed speech counts as speech. The graph also carries silence, picture notes and
// untranscribed windows; counting those inverted "when was it busy".
function isSpeech(span: Span): boolean {
  return span.kind === "speech" && (span.text.trim().length > 0 || span.raw_text.trim().length > 0);
}

function normalize(text: string): string {
  return text.normalize("NFKC").toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

const SEVERITY: Record<string, number> = { contradicted: 4, numeric_failed: 3, unresolved: 2, incomplete: 2, supported: 0 };

export function confirmationCounts(claims: Claim[]): { confirmed: number; unconfirmed: number; contradicted: number; numbers: number; total: number } {
  const worst = new Map<string, string>();
  for (const claim of claims) {
    const key = normalize(claim.text) || claim.id;
    const status = claim.status || "unresolved";
    const known = worst.get(key);
    if (known === undefined || (SEVERITY[status] ?? 2) > (SEVERITY[known] ?? 2)) worst.set(key, status);
  }
  const out = { confirmed: 0, unconfirmed: 0, contradicted: 0, numbers: 0, total: worst.size };
  for (const status of worst.values()) {
    if (status === "supported") out.confirmed += 1;
    else if (status === "contradicted") out.contradicted += 1;
    else if (status === "numeric_failed") out.numbers += 1;
    else out.unconfirmed += 1;
  }
  return out;
}

export function topicCounts(findings: Finding[]): { present: { dimension: Dimension; count: number }[]; absent: Dimension[] } {
  const counts = new Map<Dimension, number>();
  for (const finding of findings) {
    if (finding.none_in_transcript) continue;
    counts.set(finding.dimension, (counts.get(finding.dimension) ?? 0) + 1);
  }
  const present = DIMENSIONS.filter((item) => counts.has(item))
    .map((dimension) => ({ dimension, count: counts.get(dimension) ?? 0 }))
    .sort((left, right) => right.count - left.count);
  return { present, absent: DIMENSIONS.filter((item) => !counts.has(item)) };
}

/** Seconds of speech per whole minute, clipped so overlaps cannot exceed 60 s. */
export function speechPerMinute(spans: Span[]): { minute: number; seconds: number; spanId: string; startMs: number }[] {
  const timed = spans.filter((span) => isSpeech(span) && span.start_ms !== null && span.end_ms !== null);
  if (timed.length === 0) return [];
  const end = Math.max(...timed.map((span) => span.end_ms ?? 0));
  const bins = Math.max(1, Math.ceil(end / 60000));
  const rows = Array.from({ length: bins }, (_, minute) => ({ minute, seconds: 0, spanId: "", startMs: minute * 60000 }));
  for (const span of timed) {
    const start = span.start_ms ?? 0;
    const stop = Math.max(start, span.end_ms ?? start);
    for (let minute = Math.floor(start / 60000); minute <= Math.floor(Math.max(start, stop - 1) / 60000) && minute < bins; minute += 1) {
      const lo = Math.max(start, minute * 60000);
      const hi = Math.min(stop, (minute + 1) * 60000);
      if (hi > lo) rows[minute].seconds = Math.min(60, rows[minute].seconds + (hi - lo) / 1000);
      if (!rows[minute].spanId) rows[minute].spanId = span.id;
    }
  }
  return rows;
}
/**
 * "Not mentioned" is only true when the lens looked and found nothing, nothing in the meeting is
 * unconfirmed, and no part of the recording is missing. Otherwise say what is actually known.
 */
export function absenceNote(absent: Dimension[], graph: GraphPage, unconfirmed = 0): string | undefined {
  const unevaluated = absent.filter((item) => graph.not_evaluated.includes(item));
  const none = absent.filter((item) => !graph.not_evaluated.includes(item));
  const incomplete = unconfirmed > 0 || graph.spans.some((span) => span.kind === "untranscribed") || graph.gaps.length > 0;
  const parts: string[] = [];
  if (none.length > 0) {
    parts.push(
      `${incomplete ? "No confirmed points on" : "Not mentioned"}: ${none.map(dimensionTitle).join(", ")}.`,
    );
  }
  if (unevaluated.length > 0) parts.push(`Not analysed: ${unevaluated.map(dimensionTitle).join(", ")}.`);
  return parts.length > 0 ? parts.join(" ") : undefined;
}

export function buildInsights(graph: GraphPage, unconfirmed = 0): Insight[] {
  const out: Insight[] = [];
  const confirmation = confirmationCounts(graph.claims);
  if (confirmation.total > 0) {
    out.push({
      kind: "stack",
      id: "confirmation",
      title: "How much of what was found is confirmed",
      question: "Can the findings be trusted?",
      basis: `${confirmation.total} distinct statements pulled from the recording`,
      rows: [
        { key: "confirmed", label: "Confirmed by the recording", value: confirmation.confirmed, tone: "good" },
        { key: "unconfirmed", label: "Not yet confirmed", value: confirmation.unconfirmed, tone: "muted" },
        { key: "numbers", label: "Numbers need checking", value: confirmation.numbers, tone: "warn" },
        { key: "contradicted", label: "Contradicted", value: confirmation.contradicted, tone: "bad" },
      ].filter((row) => row.value > 0) as never,
    });
  }

  const topics = topicCounts(graph.findings);
  if (topics.present.length >= 2) {
    out.push({
      kind: "bars",
      id: "topics",
      title: "What the meeting covered",
      question: "Which topics came up most?",
      basis: `${topics.present.reduce((sum, row) => sum + row.count, 0)} findings across ${topics.present.length} topics`,
      rows: topics.present.map((row) => ({
        key: row.dimension,
        label: dimensionTitle(row.dimension),
        value: row.count,
        display: String(row.count),
      })),
      note: absenceNote(topics.absent, graph, unconfirmed),
    });
  }

  const activity = speechPerMinute(graph.spans);
  // A flat strip (every minute about equally busy) carries no information, so it is not drawn.
  const busiest = Math.max(0, ...activity.map((row) => row.seconds));
  const quietest = Math.min(...activity.map((row) => row.seconds));
  if (activity.length >= 3 && busiest > 0 && quietest < busiest * 0.75) {
    const timed = graph.spans.filter((span) => isSpeech(span) && span.start_ms !== null);
    const approximate = timed.length > 0 && timed.filter((span) => span.coarse).length / timed.length > 0.5;
    out.push({
      kind: "columns",
      id: "activity",
      title: "How the conversation flowed",
      question: "When was the meeting busiest and when was it quiet?",
      basis: "Seconds of speech in each minute of the recording",
      unit: "s of speech",
      rows: activity.map((row) => ({
        key: String(row.minute),
        label: `Minute ${row.minute + 1}`,
        value: Math.round(row.seconds),
        display: `${Math.round(row.seconds)} s`,
        spanId: row.spanId || null,
        startMs: row.startMs,
      })),
      note: approximate ? "Timing in this recording is approximate, so treat short gaps with care." : undefined,
    });
  }

  const byClaim = new Map(graph.claims.map((claim) => [claim.id, claim]));
  const lanes = DIMENSIONS.map((dimension) => ({
    key: dimension,
    label: dimensionTitle(dimension),
    points: graph.findings
      .filter((finding) => finding.dimension === dimension && !finding.none_in_transcript)
      .flatMap((finding) => {
        for (const claimId of finding.claim_ids) {
          const citation = byClaim.get(claimId)?.citations.find((item) => item.start_ms !== null);
          if (citation && citation.start_ms !== null) {
            return [{ id: finding.id, startMs: citation.start_ms, text: finding.text, spanId: citation.span_id }];
          }
        }
        return [];
      }),
  })).filter((lane) => lane.points.length > 0);
  const ends = graph.spans.map((span) => span.end_ms ?? 0);
  const durationMs = Math.max(1, ...ends, ...lanes.flatMap((lane) => lane.points.map((point) => point.startMs)));
  if (lanes.length > 0) {
    out.push({
      kind: "moments",
      id: "moments",
      title: "Where the key points happen",
      question: "When in the meeting was each topic discussed?",
      basis: `${lanes.reduce((sum, lane) => sum + lane.points.length, 0)} findings placed at the moment they were said`,
      durationMs,
      lanes,
    });
  }

  const named = graph.speakers.filter((row) => row.duration_ms !== null && (row.label || !/unassigned/i.test(row.id)));
  if (named.length >= 2) {
    const total = named.reduce((sum, row) => sum + (row.duration_ms ?? 0), 0);
    out.push({
      kind: "bars",
      id: "speakers",
      title: "Who did the talking",
      question: "How was speaking time shared?",
      basis: `${named.length} speakers, ${Math.round(total / 60000)} min of attributed speech`,
      rows: named
        .map((row) => ({
          key: row.id,
          label: row.label || row.id,
          value: row.duration_ms ?? 0,
          display: `${Math.round(((row.duration_ms ?? 0) / total) * 100)}%`,
        }))
        .sort((left, right) => right.value - left.value),
      note: "Speakers are identified automatically and can be wrong; rename them in the transcript.",
    });
  }
  return out;
}
