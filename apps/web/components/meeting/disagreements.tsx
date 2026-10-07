"use client";

/**
 * Motivation vs Logic
 * Motivation: Cross-modal conflicts stay as two ids and a statement.
 * Logic: The row seeks the Sonic span. The Pegasus id stays visible beside it.
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
      <p className="q-kicker">Disagreements</p>
      <h2>Cross-modal</h2>
      {rows.length === 0 ? <p className="q-muted">No disagreements on this graph page.</p> : null}
      {rows.map((row) => (
        <article key={row.id} className="q-card is-conflict">
          <p>{row.statement}</p>
          <p className="q-muted">Pegasus {row.pegasus_id}</p>
          <button className="q-btn-ghost" type="button" onClick={() => onSeek(row.sonic_span_id)}>
            Open Sonic span
          </button>
        </article>
      ))}
    </section>
  );
}
