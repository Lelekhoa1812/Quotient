"use client";

/**
 * Motivation vs Logic
 * Motivation: Statements the analysis could not confirm stay out of the brief.
 * A reader needs to see what they are, why each one is held, and hear the
 * moment, without wading through repeated extractions of the same sentence.
 * Logic: Prefer the graph's review collection; otherwise list claims whose status
 * is present and not supported. Statements are merged by normalised text and
 * status, then grouped by the reason a person would recognise: contradicted,
 * numbers to check, words not found in the recording, or found but not confirmed.
 * Server counts are shown as given. Long groups reveal 15 at a time.
 */
import { useState } from "react";
import { formatMs, formatTableNumber } from "@/lib/format";
import { claimStatusText } from "@/lib/present";
import type { Claim, MeetingStatus, Span, TranscriptGap } from "@/lib/types";

type Group = { claim: Claim; count: number };
type Bucket = { key: string; title: string; hint: string; rows: Group[] };

const PAGE = 15;

function bucketOf(claim: Claim): string {
  if (claim.status === "contradicted") return "contradicted";
  if (claim.status === "numeric_failed") return "numbers";
  if (claim.citations.length === 0) return "not-found";
  return "unconfirmed";
}

const TITLES: Record<string, [string, string]> = {
  contradicted: ["Contradicted", "Something else in the recording says the opposite."],
  numbers: ["Numbers to check", "A figure here doesn't match what was said."],
  unconfirmed: ["Heard, but not confirmed", "The words are in the recording, but the meaning could not be confirmed."],
  "not-found": ["Exact words not found", "The analysis could not locate these words in the recording."],
};

export function Review({
  claims,
  review,
  reviewPresent,
  meeting,
  onSeek,
  gaps,
  spans,
  onSeekSpan,
}: {
  claims: Claim[];
  review: Claim[];
  reviewPresent: boolean;
  meeting: MeetingStatus | null;
  onSeek: (claim: Claim) => void;
  gaps: TranscriptGap[];
  spans: Span[];
  onSeekSpan: (span: Span) => void;
}) {
  const rows = reviewPresent ? review : claims.filter((claim) => claim.status.length > 0 && claim.status !== "supported");
  const groups = new Map<string, Group>();
  for (const claim of rows) {
    const normalized = claim.text.normalize("NFKC").toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
    const key = `${bucketOf(claim)}\u0000${normalized || claim.id}`;
    const group = groups.get(key);
    if (group) {
      group.count += 1;
      if (group.claim.citations.length === 0 && claim.citations.length > 0) group.claim = claim;
    } else groups.set(key, { claim, count: 1 });
  }
  const buckets: Bucket[] = ["contradicted", "numbers", "unconfirmed", "not-found"]
    .map((key) => ({
      key,
      title: TITLES[key][0],
      hint: TITLES[key][1],
      rows: [...groups.entries()].filter(([id]) => id.startsWith(`${key}\u0000`)).map(([, group]) => group),
    }))
    .filter((bucket) => bucket.rows.length > 0);
  const distinct = groups.size;
  const counts = meeting?.reviewCounts;

  return (
    <section className="q-section">
      <div>
        <h2>To check</h2>
        <p className="q-lede">
          Statements the analysis couldn't confirm against the recording. They are left out of the brief, so the brief only says what was confirmed. Play any moment to check it yourself.
        </p>
      </div>
      {distinct > 0 ? (
        <p className="q-summary">
          <strong>{formatTableNumber(distinct)}</strong> {distinct === 1 ? "statement" : "different statements"} to check
          {rows.length > distinct ? ` (found ${formatTableNumber(rows.length)} times in total)` : ""}
          {counts?.contradicted ? ` · ${formatTableNumber(counts.contradicted)} contradicted` : ""}
        </p>
      ) : null}
      {rows.length === 0 && gaps.length === 0 ? <p className="q-empty">Nothing needs checking.</p> : null}
      {buckets.map((bucket) => (
        <BucketView key={bucket.key} bucket={bucket} onSeek={onSeek} />
      ))}
      {gaps.length > 0 ? (
        <details className="q-details">
          <summary>Parts of the recording the analysis could not account for ({gaps.length})</summary>
          <div className="q-cards">
            {gaps.map((gap) => (
              <article key={gap.id} className="q-card">
                <p className="q-muted">{gap.reason || "The analysis could not turn this part into a statement."}</p>
                {gap.spanIds.map((spanId) => {
                  const span = spans.find((item) => item.id === spanId);
                  return span ? (
                    <div key={spanId}>
                      <p>{span.text || span.raw_text || (span.start_ms !== null ? `The recording from ${formatMs(span.start_ms)}.` : "This part of the recording.")}</p>
                      <button className="q-btn-ghost" type="button" onClick={() => onSeekSpan(span)}>Hear this part</button>
                    </div>
                  ) : null;
                })}
              </article>
            ))}
          </div>
        </details>
      ) : null}
    </section>
  );
}

function BucketView({ bucket, onSeek }: { bucket: Bucket; onSeek: (claim: Claim) => void }) {
  const [shown, setShown] = useState(PAGE);
  return (
    <div className="q-cards">
      <div>
        <h3>{bucket.title} <span className="q-badge">{bucket.rows.length}</span></h3>
        <p className="q-muted">{bucket.hint}</p>
      </div>
      {bucket.rows.slice(0, shown).map(({ claim, count }) => (
        <article key={claim.id} className="q-card">
          <p>{claim.text || "Statement without text"}</p>
          <div className="q-inline">
            <span className="q-meta">{claimStatusText(claim.status)}</span>
            {count > 1 ? <span className="q-muted">Mentioned {count} times</span> : null}
          </div>
          {claim.citations.length > 0 ? (
            <button className="q-btn-ghost" type="button" onClick={() => onSeek(claim)}>Hear the moment</button>
          ) : (
            <p className="q-muted">No matching moment could be found in the recording.</p>
          )}
        </article>
      ))}
      {bucket.rows.length > shown ? (
        <button className="q-btn-ghost" type="button" onClick={() => setShown(shown + PAGE)}>
          Show {Math.min(PAGE, bucket.rows.length - shown)} more
        </button>
      ) : null}
    </div>
  );
}
