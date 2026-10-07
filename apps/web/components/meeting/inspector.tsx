"use client";

/**
 * Motivation vs Logic
 * Motivation: Opening a synthesis sentence reveals findings before the span.
 * Logic: The panel keeps the finding list mounted, then appends the span once
 * read_span returns. Quote text is marked only on an exact slice.
 */
import { quoteParts, speakerText } from "@/lib/format";
import { formatMs } from "@/lib/format";
import type { Citation, Finding, Span } from "@/lib/types";

export function Inspector({
  findings,
  span,
  citation,
  phase,
}: {
  findings: Finding[];
  span: Span | null;
  citation: Citation | null;
  phase: "idle" | "findings" | "span";
}) {
  return (
    <aside className="q-inspector" aria-live="polite">
      <p className="q-kicker">Inspector</p>
      {phase === "idle" ? <p className="q-muted">Select a synthesis sentence to open its findings.</p> : null}
      {findings.length > 0 ? (
        <div className="q-cards">
          <h2>Findings</h2>
          {findings.map((finding) => (
            <article key={finding.id} className={finding.stance === "conflicts" ? "q-card is-conflict" : "q-card"}>
              <p className="q-kicker">{finding.dimension}</p>
              <p className="q-kicker">{finding.stance}</p>
              <p>{finding.text}</p>
            </article>
          ))}
        </div>
      ) : null}
      {phase === "span" && span ? (
        <div className="q-card">
          <p className="q-kicker">Span</p>
          <p className="q-kicker">{speakerText(span)}</p>
          {span.start_ms !== null ? <p className="q-muted">{formatMs(span.start_ms)}</p> : null}
          <div className="q-inline">
            {span.coarse ? <span className="q-badge">Coarse</span> : null}
            {span.overlap ? <span className="q-badge">Overlap</span> : null}
          </div>
          <p className="q-meta">Synthesized</p>
          <Highlighted text={span.text} citation={citation} />
          <p className="q-meta">Raw</p>
          <p>{span.raw_text || "No raw text on this span."}</p>
        </div>
      ) : null}
    </aside>
  );
}

function Highlighted({ text, citation }: { text: string; citation: Citation | null }) {
  const parts = quoteParts(text, citation);
  if (!parts) return <p>{text}</p>;
  return <p>{parts.before}<mark>{parts.quote}</mark>{parts.after}</p>;
}
