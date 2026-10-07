"use client";

/**
 * Motivation vs Logic
 * Motivation: Unresolved and contradicted claims stay out of the brief and in
 * the review queue.
 * Logic: Prefer the graph's review collection. Otherwise list claims whose
 * status is present and not supported. Server counts are printed as given.
 */
import { formatTableNumber, statusLabel } from "@/lib/format";
import type { Claim, MeetingStatus } from "@/lib/types";

export function Review({
  claims,
  review,
  reviewPresent,
  meeting,
  onSeek,
}: {
  claims: Claim[];
  review: Claim[];
  reviewPresent: boolean;
  meeting: MeetingStatus | null;
  onSeek: (claim: Claim) => void;
}) {
  const rows = reviewPresent ? review : claims.filter((claim) => claim.status.length > 0 && claim.status !== "supported");
  const counts = meeting?.reviewCounts;
  return (
    <section className="q-section">
      <div>
        <h2>To review</h2>
        <p className="q-lede">These points stay out of the written brief until someone checks them.</p>
      </div>
      {counts ? (
        <div className="q-inline">
          {counts.unresolved !== null ? <span className="q-badge">Unresolved {formatTableNumber(counts.unresolved)}</span> : null}
          {counts.contradicted !== null ? <span className="q-badge">Contradicted {formatTableNumber(counts.contradicted)}</span> : null}
          {counts.numeric_failed !== null ? <span className="q-badge">Numbers to check {formatTableNumber(counts.numeric_failed)}</span> : null}
        </div>
      ) : null}
      {rows.length === 0 ? <p className="q-empty">The review queue is empty.</p> : null}
      {rows.map((claim) => (
        <article key={claim.id} className="q-card">
          <div className="q-inline">
            {claim.status ? <span className="q-badge">{statusLabel(claim.status)}</span> : null}
            {claim.coarse ? <span className="q-badge">Coarse</span> : null}
            {claim.overlap ? <span className="q-badge">Overlap</span> : null}
          </div>
          <p>{claim.text || claim.id}</p>
          <button className="q-btn-ghost" type="button" onClick={() => onSeek(claim)}>Open cited span</button>
        </article>
      ))}
    </section>
  );
}
