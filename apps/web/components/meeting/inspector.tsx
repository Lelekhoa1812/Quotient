"use client";

/**
 * Motivation vs Logic
 * Motivation: Opening a brief sentence or a claim has to show what supports it:
 * the quote, who said it, and when, without engineering detail.
 * Logic: The panel exists only while something is selected. It lists the
 * findings, then the cited moment with the quote highlighted when the stored
 * offsets slice to exactly that quote. The worker's cleaned text and the raw
 * transcript are shown as "what was understood" and "what was heard".
 */
import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { formatMs, quoteParts } from "@/lib/format";
import { dimensionTitle, speakerName, stanceText } from "@/lib/present";
import type { Citation, Finding, Span } from "@/lib/types";

export function Inspector({
  findings,
  span,
  citation,
  phase,
  onClose,
}: {
  findings: Finding[];
  span: Span | null;
  citation: Citation | null;
  phase: "idle" | "findings" | "span";
  onClose: () => void;
}) {
  const ref = useRef<HTMLElement>(null);
  // When the layout stacks (narrow windows) the panel opens below the page; bring it into view.
  useEffect(() => {
    if (typeof window !== "undefined" && window.matchMedia("(max-width: 1180px)").matches) {
      ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [span?.id, findings.length]);

  return (
    <aside className="q-inspector" aria-label="Supporting evidence" ref={ref}>
      <div className="q-inspector-head">
        <h2>Supporting evidence</h2>
        <button className="q-icon-btn" type="button" onClick={onClose} aria-label="Close evidence panel">
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <div aria-live="polite" className="q-cards">
        {findings.map((finding) => (
          <article key={finding.id} className={finding.stance === "conflicts" ? "q-card is-conflict" : "q-card"}>
            <p className="q-meta">{dimensionTitle(finding.dimension)} · {stanceText(finding.stance)}</p>
            <p>{finding.text}</p>
          </article>
        ))}
        {phase === "span" && span ? (
          <article className="q-card">
            <p className="q-meta">
              {speakerName(span.speaker_label, span.speaker_hypothesis_id)}
              {span.start_ms !== null ? ` · ${formatMs(span.start_ms)}` : ""}
            </p>
            <h3>What was understood</h3>
            <Highlighted text={span.text} citation={citation} />
            {span.raw_text && span.raw_text !== span.text ? (
              <>
                <h3>What was heard</h3>
                <p className="q-muted">{span.raw_text}</p>
              </>
            ) : null}
            {span.coarse ? <p className="q-muted">The exact timing of this moment is approximate.</p> : null}
          </article>
        ) : null}
        {phase === "findings" ? <p className="q-muted">Finding the supporting moment…</p> : null}
      </div>
    </aside>
  );
}

function Highlighted({ text, citation }: { text: string; citation: Citation | null }) {
  const parts = quoteParts(text, citation);
  if (!parts) return <p>{text}</p>;
  return <p>{parts.before}<mark>{parts.quote}</mark>{parts.after}</p>;
}
