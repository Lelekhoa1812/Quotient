"use client";

/**
 * Motivation vs Logic
 * Motivation: Raw evidence and synthesized analysis have to stay readable at
 * the same time. A click on a raw sentence seeks only when a span id exists.
 * Logic: Audio raw is span.raw_text. Video raw is observation statements, plus
 * a meeting-level raw_transcript string when the graph includes one. Synthesized
 * text is span.text and the brief. Empty raw stays on the page. Brief
 * sentences render markdown, including a mermaid fence, in reading order.
 */
import { useState } from "react";
import { Markdown } from "@/components/markdown";
import { formatMs, formatTableNumber, quoteParts, speakerText } from "@/lib/format";
import { timelineSeams } from "@/lib/graph";
import type { Citation, RawTranscript, Seam, Span, SpeakerHypothesis, SynthesisSentence, VideoObservation } from "@/lib/types";

const VIDEO_KIND = new Set(["video", "visual", "observation", "pegasus", "visual-idle", "visual_idle"]);

export function Transcript({
  spans,
  seams,
  omissions,
  rawTranscript,
  observations,
  speakers,
  synthesis,
  activeId,
  citation,
  onSeek,
  onOpenSentence,
  onReviseText,
  onReviseSpeaker,
}: {
  spans: Span[];
  seams: Seam[];
  omissions: { span_id: string; reason: string }[];
  rawTranscript: RawTranscript;
  observations: VideoObservation[];
  speakers: SpeakerHypothesis[];
  synthesis: SynthesisSentence[];
  activeId: string | null;
  citation: Citation | null;
  onSeek: (span: Span) => void;
  onOpenSentence: (sentence: SynthesisSentence) => void;
  onReviseText: (span: Span, text: string) => Promise<void>;
  onReviseSpeaker: (span: Span, scope: "span" | "hypothesis", displayName: string) => Promise<void>;
}) {
  const ordered = spans.slice().sort((left, right) => (left.start_ms ?? 0) - (right.start_ms ?? 0));
  const marks = new Set(timelineSeams(spans, seams).map((mark) => mark.at_ms));
  const audio = ordered.filter((span) => !VIDEO_KIND.has(span.kind) && span.raw_text.trim().length > 0);
  const videoSpans = ordered.filter((span) => VIDEO_KIND.has(span.kind) && span.raw_text.trim().length > 0);
  const videoSeen = new Set(videoSpans.map((span) => `${span.start_ms ?? ""}:${span.raw_text}`));
  const videoNotes = observations.filter((item) => !videoSeen.has(`${item.start_ms ?? ""}:${item.statement}`));
  const synthesized = ordered.filter((span) => span.text.trim().length > 0);
  const audioEmpty = audio.length === 0 && rawTranscript.audio.trim().length === 0;
  const videoEmpty = videoSpans.length === 0 && videoNotes.length === 0 && rawTranscript.video.trim().length === 0;

  return (
    <section className="q-section">
      <div>
        <p className="q-kicker">Transcript</p>
        <h2>Two records</h2>
        <p className="q-lede">Raw is the evidence. Synthesized is the analysis text. They stay separate.</p>
      </div>
      <Hypotheses speakers={speakers} />
      <div className="q-transcripts">
        <div className="q-pane">
          <h2>Raw</h2>
          <p className="q-muted">Immutable audio and video transcription.</p>
          <h3>Audio</h3>
          {rawTranscript.audio.trim() ? <p className="q-block">{rawTranscript.audio}</p> : null}
          {audioEmpty ? <p className="q-empty">No raw audio on this graph page.</p> : null}
          {audio.map((span) => (
            <RawRow
              key={span.id}
              span={span}
              body={span.raw_text}
              active={span.id === activeId}
              citation={span.id === citation?.span_id ? citation : null}
              seam={span.start_ms !== null && marks.has(span.start_ms)}
              onSeek={onSeek}
            />
          ))}
          <h3>Video</h3>
          {rawTranscript.video.trim() ? <p className="q-block">{rawTranscript.video}</p> : null}
          {videoEmpty ? <p className="q-empty">No raw video on this graph page.</p> : null}
          {videoSpans.map((span) => (
            <RawRow
              key={span.id}
              span={span}
              body={span.raw_text}
              active={span.id === activeId}
              citation={null}
              seam={span.start_ms !== null && marks.has(span.start_ms)}
              onSeek={onSeek}
            />
          ))}
          {videoNotes.map((item) => {
            const span = item.id ? ordered.find((candidate) => candidate.id === item.id) ?? null : null;
            return (
              <article key={`${item.id ?? "video"}:${item.start_ms ?? "t"}:${item.statement}`} className={span && span.id === activeId ? "q-card is-on" : "q-card"}>
                <div className="q-inline">
                  <span className="q-meta">Video</span>
                  {item.start_ms !== null ? <span className="q-muted q-num">{formatMs(item.start_ms)}</span> : null}
                </div>
                <p>{item.statement}</p>
                {span ? (
                  <button className="q-btn-ghost" type="button" onClick={() => onSeek(span)}>Open span</button>
                ) : (
                  <p className="q-muted">No span id on this observation.</p>
                )}
              </article>
            );
          })}
        </div>
        <div className="q-pane">
          <h2>Synthesized</h2>
          <p className="q-muted">Analysis text. The brief cites findings. The review queue is not part of this brief.</p>
          <h3>Brief</h3>
          {synthesis.length === 0 ? <p className="q-empty">No brief sentences on this graph page.</p> : null}
          {synthesis.map((sentence) => (
            <article
              key={sentence.id}
              className="q-sentence"
              role="button"
              tabIndex={0}
              onClick={() => onOpenSentence(sentence)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onOpenSentence(sentence);
                }
              }}
            >
              <Markdown text={sentence.text} />
            </article>
          ))}
          <h3>Span text</h3>
          {synthesized.length === 0 ? <p className="q-empty">No synthesized span text on this graph page.</p> : null}
          {synthesized.map((span) => (
            <article key={span.id} className={span.id === activeId ? "q-card is-on" : "q-card"}>
              <div className="q-inline">
                <span className="q-meta">{speakerText(span)}</span>
                {span.start_ms !== null ? <span className="q-muted q-num">{formatMs(span.start_ms)}</span> : null}
                {span.coarse ? <span className="q-badge">Coarse</span> : null}
                {span.overlap ? <span className="q-badge">Overlap</span> : null}
              </div>
              <Highlighted text={span.text} citation={span.id === citation?.span_id ? citation : null} />
              {omissions.filter((item) => item.span_id === span.id).map((item) => (
                <p key={`${span.id}:${item.reason}`} className="q-muted">Omission: {item.reason || "recorded"}</p>
              ))}
              <button className="q-btn-ghost" type="button" onClick={() => onSeek(span)}>Open span</button>
              <SpanEdit span={span} onReviseText={onReviseText} onReviseSpeaker={onReviseSpeaker} />
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function Hypotheses({ speakers }: { speakers: SpeakerHypothesis[] }) {
  return (
    <div className="q-pane">
      <h3>Speaker hypotheses</h3>
      <p className="q-muted">Duration, share, and turn count are hypotheses. This page does not compute them.</p>
      {speakers.length === 0 ? <p className="q-empty">No speaker hypothesis measures on this graph page.</p> : null}
      {speakers.length > 0 ? (
        <table className="q-table">
          <thead>
            <tr>
              <th>Hypothesis</th>
              <th>Duration ms</th>
              <th>Share</th>
              <th>Turns</th>
            </tr>
          </thead>
          <tbody>
            {speakers.map((row) => (
              <tr key={row.id}>
                <td>{row.label || row.id}</td>
                <td className="q-num">{row.duration_ms === null ? "" : formatTableNumber(row.duration_ms)}</td>
                <td className="q-num">{row.duration_share === null ? "" : formatTableNumber(row.duration_share)}</td>
                <td className="q-num">{row.turn_count === null ? "" : formatTableNumber(row.turn_count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}

function RawRow({
  span,
  body,
  active,
  citation,
  seam,
  onSeek,
}: {
  span: Span;
  body: string;
  active: boolean;
  citation: Citation | null;
  seam: boolean;
  onSeek: (span: Span) => void;
}) {
  return (
    <article className={active ? "q-card is-on" : "q-card"}>
      {seam ? <p className="q-meta">Seam</p> : null}
      <div className="q-inline">
        <span className="q-meta">{speakerText(span)}</span>
        {span.start_ms !== null ? <span className="q-muted q-num">{formatMs(span.start_ms)}</span> : null}
        {span.coarse ? <span className="q-badge">Coarse</span> : null}
      </div>
      <Highlighted text={body} citation={citation} />
      <button className="q-btn-ghost" type="button" onClick={() => onSeek(span)}>Open span</button>
    </article>
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
  return (
    <details>
      <summary>Revise synthesized text or speaker</summary>
      <div className="q-stack">
        <label className="q-label">
          Synthesized text
          <textarea className="q-area" value={text} onChange={(event) => setText(event.target.value)} />
        </label>
        <button
          className="q-btn-ghost"
          type="button"
          onClick={() => {
            void onReviseText(span, text).then(() => setMessage("Text sent")).catch((error: unknown) => {
              setMessage(error instanceof Error ? error.message : "revise_text failed");
            });
          }}
        >
          Save text
        </button>
        <label className="q-label">
          Display name
          <input className="q-field" value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <div className="q-inline">
          <button className="q-btn-ghost" type="button" disabled={name.trim().length === 0} onClick={() => void send("span")}>This span</button>
          <button
            className="q-btn-ghost"
            type="button"
            disabled={name.trim().length === 0 || !span.speaker_hypothesis_id}
            onClick={() => void send("hypothesis")}
          >
            This hypothesis
          </button>
        </div>
        {message ? <p role="status">{message}</p> : null}
      </div>
    </details>
  );

  function send(scope: "span" | "hypothesis") {
    return onReviseSpeaker(span, scope, name.trim()).then(() => setMessage("Speaker sent")).catch((error: unknown) => {
      setMessage(error instanceof Error ? error.message : "revise_speaker failed");
    });
  }
}
