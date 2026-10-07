"use client";

/**
 * Motivation vs Logic
 * Motivation: The transcript timeline has to show coarse spans and session
 * seams on the source clock, including regions omitted from model payloads.
 * Logic: Place each span by start_ms and end_ms. Coarse spans get a hatch and
 * a kicker. Seam ticks come from seam records and session handoffs.
 */
import { formatMs } from "@/lib/format";
import { timelineSeams } from "@/lib/graph";
import type { Seam, Span } from "@/lib/types";

export function Timeline({
  spans,
  seams,
  activeId,
  onSeek,
}: {
  spans: Span[];
  seams: Seam[];
  activeId: string | null;
  onSeek: (span: Span) => void;
}) {
  const timed = spans.filter((span) => span.start_ms !== null && span.end_ms !== null);
  const duration = Math.max(1, ...timed.map((span) => span.end_ms ?? 0));
  const marks = timelineSeams(spans, seams);
  return (
    <div className="q-timeline" role="list" aria-label="Transcript timeline">
      {marks.map((mark) => (
        <div key={`${mark.at_ms}:${mark.session_id}`} className="q-seam" style={{ left: `${(mark.at_ms / duration) * 100}%` }}>
          <span className="q-kicker">Seam</span>
        </div>
      ))}
      {timed.map((span) => {
        const start = span.start_ms ?? 0;
        const end = Math.max(start, span.end_ms ?? start);
        const width = Math.max(0.8, ((end - start) / duration) * 100);
        return (
          <button
            key={span.id}
            type="button"
            role="listitem"
            className={["q-span", span.coarse ? "q-coarse" : "", span.id === activeId ? "is-on" : ""].filter(Boolean).join(" ")}
            style={{ left: `${(start / duration) * 100}%`, width: `${width}%` }}
            title={span.text}
            onClick={() => onSeek(span)}
          >
            {span.coarse ? <span className="q-kicker">Coarse</span> : <span className="q-sr">{formatMs(start)}</span>}
          </button>
        );
      })}
    </div>
  );
}
