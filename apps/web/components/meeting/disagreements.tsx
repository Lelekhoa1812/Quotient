"use client";

/**
 * Motivation vs Logic
 * Motivation: When what was said and what was shown disagree, the reader needs
 * the statement and a way to hear the moment, not worker identifiers.
 * Logic: Each row keeps its two stored ids for provenance but renders only the
 * statement and a button that seeks the spoken moment.
 */
import type { Disagreement } from "@/lib/types";

export function Disagreements({
  rows,
  onSeek,
}: {
  rows: Disagreement[];
  onSeek: (spanId: string) => void;
}) {
  return (
    <section className="q-cards">
      <div>
        <h2>Audio vs video</h2>
        <p className="q-lede">Places where what was said does not match what was shown.</p>
      </div>
      {rows.length === 0 ? <p className="q-empty">No mismatches between the audio and the video were found.</p> : null}
      {rows.map((row) => (
        <article key={row.id} className="q-card is-conflict" data-source={`${row.sonic_span_id}:${row.pegasus_id}`}>
          <p>{row.statement}</p>
          <button className="q-btn-ghost" type="button" onClick={() => onSeek(row.sonic_span_id)}>
            Hear this moment
          </button>
        </article>
      ))}
    </section>
  );
}
