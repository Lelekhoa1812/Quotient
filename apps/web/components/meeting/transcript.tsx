"use client";

/**
 * Motivation vs Logic
 * Motivation: People read a transcript as one conversation in time order, can
 * search it, and jump to the recording from any line. The worker's cleaned text
 * and the original wording are both evidence, but only one is the default view.
 * Logic: Spans sort by start_ms into one list. Each line shows the speaker, the
 * time, and the understood text; "Original wording" reveals raw_text when it
 * differs. Video observations are interleaved as "On screen" notes. Citation
 * quotes are highlighted only on an exact slice. Edits go through the same
 * revise_text and revise_speaker calls as before.
 */
import { useEffect, useMemo, useState } from "react";
import { formatMs, quoteParts, speakerText } from "@/lib/format";
import { friendlyError } from "@/lib/present";
import type { Citation, Span, VideoObservation } from "@/lib/types";

const VIDEO_KIND = new Set(["video", "visual", "observation", "pegasus", "visual-idle", "visual_idle"]);

export function Transcript({
  spans,
  observations,
  activeId,
  citation,
  onSeek,
  onReviseText,
  onReviseSpeaker,
}: {
  spans: Span[];
  observations: VideoObservation[];
  activeId: string | null;
  citation: Citation | null;
  onSeek: (span: Span) => void;
  onReviseText: (span: Span, text: string) => Promise<void>;
  onReviseSpeaker: (span: Span, scope: "span" | "hypothesis", displayName: string) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  // A long meeting has well over a thousand lines; draw them in pages. Searching shows every match.
  const PAGE = 300;
  const [limit, setLimit] = useState(PAGE);
  const ordered = useMemo(
    () => spans.slice().sort((left, right) => (left.start_ms ?? 0) - (right.start_ms ?? 0)),
    [spans],
  );
  const speech = ordered.filter(
    (span) => span.kind === "untranscribed" || (!VIDEO_KIND.has(span.kind) && (span.text.trim() || span.raw_text.trim())),
  );
  const seen = new Set(
    ordered.filter((span) => VIDEO_KIND.has(span.kind)).map((span) => `${span.start_ms ?? ""}:${span.raw_text}`),
  );
  const screen = [
    ...ordered
      .filter((span) => VIDEO_KIND.has(span.kind) && span.raw_text.trim())
      .map((span) => ({ key: span.id, at: span.start_ms, text: span.raw_text, span })),
    ...observations
      .filter((item) => !seen.has(`${item.start_ms ?? ""}:${item.statement}`))
      .map((item) => ({
        key: `${item.id ?? "obs"}:${item.start_ms ?? "t"}:${item.statement.slice(0, 24)}`,
        at: item.start_ms,
        text: item.statement,
        span: item.id ? ordered.find((candidate) => candidate.id === item.id) ?? null : null,
      })),
  ];
  const needle = query.trim().toLocaleLowerCase();
  const matching = speech.filter(
    (span) => span.kind === "untranscribed" ? !needle : !needle || `${span.text} ${span.raw_text}`.toLocaleLowerCase().includes(needle),
  );
  const rows = needle ? matching : matching.slice(0, limit);
  // A line selected from elsewhere (a citation) must be on the page.
  const activeIndex = activeId ? matching.findIndex((span) => span.id === activeId) : -1;
  useEffect(() => {
    if (!needle && activeIndex >= limit) setLimit(activeIndex + 50);
  }, [activeIndex, limit, needle]);

  return (
    <section className="q-section">
      <div>
        <h2>Transcript</h2>
        <p className="q-lede">Everything that was said, in order. Select a line to hear it.</p>
      </div>
      <label className="q-search q-search-wide">
        <span className="q-sr">Search the transcript</span>
        <input
          type="search"
          value={query}
          placeholder="Search the transcript"
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      {speech.length === 0 ? <p className="q-empty">No transcript is available for this meeting.</p> : null}
      {speech.length > 0 && rows.length === 0 ? <p className="q-empty">Nothing in the transcript matches “{query}”.</p> : null}
      <ol className="q-lines">
        {rows.map((span) => span.kind === "untranscribed" ? (
          <li key={span.id} className="q-line q-line-gap">
            <div className="q-line-head">
              {span.start_ms !== null ? (
                <button className="q-time" type="button" onClick={() => onSeek(span)} aria-label={`Play from ${formatMs(span.start_ms)}`}>{formatMs(span.start_ms)}</button>
              ) : null}
              <span className="q-speaker">Not transcribed</span>
            </div>
            <p className="q-muted">
              This part of the recording{span.start_ms !== null && span.end_ms !== null ? ` (${formatMs(span.start_ms)} to ${formatMs(span.end_ms)})` : ""} could
              not be transcribed. Nothing from it is in the transcript or the brief.
            </p>
          </li>
        ) : (
          <Line
            key={span.id}
            span={span}
            active={span.id === activeId}
            citation={span.id === citation?.span_id ? citation : null}
            onSeek={onSeek}
            onReviseText={onReviseText}
            onReviseSpeaker={onReviseSpeaker}
          />
        ))}
      </ol>
      {!needle && matching.length > rows.length ? (
        <div className="q-inline">
          <button className="q-btn-ghost" type="button" onClick={() => setLimit(limit + PAGE)}>
            Show {Math.min(PAGE, matching.length - rows.length)} more lines ({matching.length - rows.length} not shown)
          </button>
          <button className="q-btn-ghost" type="button" onClick={() => setLimit(matching.length)}>Show everything</button>
        </div>
      ) : null}
      {screen.length > 0 && !needle ? (
        <details className="q-details">
          <summary>What was shown on screen ({screen.length})</summary>
          <ul className="q-lines">
            {screen.map((item) => (
              <li key={item.key} className="q-line">
                <div className="q-line-head">
                  {item.at !== null ? (
                    item.span ? (
                      <button className="q-time" type="button" onClick={() => onSeek(item.span as Span)}>{formatMs(item.at)}</button>
                    ) : (
                      <span className="q-time is-static">{formatMs(item.at)}</span>
                    )
                  ) : null}
                </div>
                <p>{item.text}</p>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}

function Line({
  span,
  active,
  citation,
  onSeek,
  onReviseText,
  onReviseSpeaker,
}: {
  span: Span;
  active: boolean;
  citation: Citation | null;
  onSeek: (span: Span) => void;
  onReviseText: (span: Span, text: string) => Promise<void>;
  onReviseSpeaker: (span: Span, scope: "span" | "hypothesis", displayName: string) => Promise<void>;
}) {
  const body = span.text.trim() ? span.text : span.raw_text;
  const differs = span.raw_text.trim() && span.raw_text.trim() !== body.trim();
  return (
    <li className={active ? "q-line is-on" : "q-line"}>
      <div className="q-line-head">
        {span.start_ms !== null ? (
          <button className="q-time" type="button" onClick={() => onSeek(span)} aria-label={`Play from ${formatMs(span.start_ms)}`}>
            {formatMs(span.start_ms)}
          </button>
        ) : null}
        <span className="q-speaker">{speakerText(span)}</span>
      </div>
      <Highlighted text={body} citation={citation} />
      {differs ? (
        <details className="q-details q-inline-details">
          <summary>Original wording</summary>
          <p className="q-muted">{span.raw_text}</p>
        </details>
      ) : null}
      <SpanEdit span={span} onReviseText={onReviseText} onReviseSpeaker={onReviseSpeaker} />
    </li>
  );
}

function Highlighted({ text, citation }: { text: string; citation: Citation | null }) {
  const parts = quoteParts(text, citation);
  if (!parts) return <p>{text}</p>;
  return <p>{parts.before}<mark>{parts.quote}</mark>{parts.after}</p>;
}

function SpanEdit({
  span,
  onReviseText,
  onReviseSpeaker,
}: {
  span: Span;
  onReviseText: (span: Span, text: string) => Promise<void>;
  onReviseSpeaker: (span: Span, scope: "span" | "hypothesis", displayName: string) => Promise<void>;
}) {
  const [text, setText] = useState(span.text);
  const [name, setName] = useState(span.speaker_label ?? "");
  const [message, setMessage] = useState("");

  function saveText() {
    setMessage("");
    onReviseText(span, text).then(
      () => setMessage("Saved"),
      (error: unknown) => setMessage(friendlyError(error instanceof Error ? error.message : null, "Could not save. Please try again.")),
    );
  }

  function saveSpeaker(scope: "span" | "hypothesis") {
    setMessage("");
    onReviseSpeaker(span, scope, name.trim()).then(
      () => setMessage("Saved"),
      (error: unknown) => setMessage(friendlyError(error instanceof Error ? error.message : null, "Could not save. Please try again.")),
    );
  }

  return (
    <details className="q-details q-inline-details">
      <summary>Correct this line</summary>
      <div className="q-stack">
        <label className="q-label">
          Text
          <textarea className="q-area" value={text} onChange={(event) => setText(event.target.value)} />
        </label>
        <div className="q-inline">
          <button className="q-btn-ghost" type="button" onClick={saveText}>Save text</button>
        </div>
        <label className="q-label">
          Speaker name
          <input className="q-field" value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <div className="q-inline">
          <button className="q-btn-ghost" type="button" disabled={name.trim().length === 0} onClick={() => saveSpeaker("span")}>
            Apply to this line
          </button>
          <button
            className="q-btn-ghost"
            type="button"
            disabled={name.trim().length === 0 || !span.speaker_hypothesis_id}
            onClick={() => saveSpeaker("hypothesis")}
          >
            Apply to this speaker everywhere
          </button>
        </div>
        {message ? <p role="status">{message}</p> : null}
      </div>
    </details>
  );
}
