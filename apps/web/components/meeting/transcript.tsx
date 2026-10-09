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
 * revise_text and revise_speaker calls as before. Clicking a speaker's name focuses that voice:
 * the other lines are dimmed so one person's turns can be followed. Double-clicking the name
 * renames the whole voice in place.
 * The line being played is highlighted and, while "Follow" is on, kept in view. Topic
 * headings from the digest's chapters are placed before their first line. Each voice gets
 * a stable colour so turns are easy to follow.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Crosshair, Pencil } from "lucide-react";
import { IconButton } from "@/components/ui/moment";
import { VoiceName } from "@/components/meeting/voices";
import type { Chapter } from "@/lib/digest";
import { formatMs, quoteParts, speakerText } from "@/lib/format";
import { voiceStats } from "@/lib/analytics";
import { friendlyError, speakerName } from "@/lib/present";
import type { Citation, Span, VideoObservation } from "@/lib/types";

/** The voice's rank by speaking time, the order the Insights charts colour them in. */
function voiceOf(span: Span, ranks: Map<string, number>): number {
  const rank = span.speaker_hypothesis_id ? ranks.get(span.speaker_hypothesis_id) : undefined;
  return rank === undefined ? -1 : Math.min(rank, 7); // the eighth colour is the neutral grey shared by every further voice
}

const VIDEO_KIND = new Set(["video", "visual", "observation", "pegasus", "visual-idle", "visual_idle"]);

export function Transcript({
  spans,
  observations,
  names = new Map<string, string>(),
  chapters = [],
  nowMs = 0,
  activeId,
  citation,
  onSeek,
  onReviseText,
  onReviseSpeaker,
}: {
  spans: Span[];
  observations: VideoObservation[];
  names?: Map<string, string>;
  chapters?: Chapter[];
  nowMs?: number;
  activeId: string | null;
  citation: Citation | null;
  onSeek: (span: Span) => void;
  onReviseText: (span: Span, text: string) => Promise<void>;
  onReviseSpeaker: (span: Span, scope: "span" | "hypothesis", displayName: string) => Promise<void>;
}) {
  const ranks = useMemo(() => new Map(voiceStats(spans, names).map((voice, index) => [voice.id, index] as const)), [spans, names]);
  const [query, setQuery] = useState("");
  const [follow, setFollow] = useState(true);
  const [focusVoice, setFocusVoice] = useState<string | null>(null);
  const lineRefs = useRef(new Map<string, HTMLLIElement>());
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

  // The line being played: the last line that has started.
  let playingId: string | null = null;
  if (nowMs > 0) {
    for (const span of speech) {
      if (span.start_ms !== null && span.start_ms <= nowMs) playingId = span.id;
      else if (span.start_ms !== null) break;
    }
  }
  const playingIndex = playingId ? matching.findIndex((span) => span.id === playingId) : -1;
  // A reader who scrolls away is not pulled back: any wheel, touch or paging key pauses following.
  useEffect(() => {
    const pause = () => setFollow(false);
    const onKey = (event: KeyboardEvent) => {
      if (["PageUp", "PageDown", "Home", "End"].includes(event.key)) pause();
    };
    window.addEventListener("wheel", pause, { passive: true });
    window.addEventListener("touchmove", pause, { passive: true });
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("wheel", pause);
      window.removeEventListener("touchmove", pause);
      window.removeEventListener("keydown", onKey);
    };
  }, []);
  useEffect(() => {
    if (!follow || !playingId || needle) return;
    if (playingIndex >= limit) setLimit(playingIndex + 50);
    lineRefs.current.get(playingId)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [follow, playingId, playingIndex, limit, needle]);

  // Topic headings go before the first line at or after each chapter start.
  const headingBefore = new Map<string, Chapter>();
  if (!needle) {
    for (const chapter of chapters) {
      const first = rows.find((span) => (span.start_ms ?? 0) >= chapter.startMs);
      if (first && !headingBefore.has(first.id)) headingBefore.set(first.id, chapter);
    }
  }

  return (
    <section className="q-section">
      <div className="q-toolbar">
        <label className="q-search q-search-wide">
          <span className="q-sr">Search the transcript</span>
          <input
            type="search"
            value={query}
            placeholder="Search the transcript"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <IconButton label="Follow playback" pressed={follow} onClick={() => setFollow((value) => !value)}>
          <Crosshair size={16} aria-hidden="true" />
        </IconButton>
      </div>
      {focusVoice ? (
        <div className="q-inline">
          <span className="q-faint">Focused on {names.get(focusVoice) ?? speakerName(null, focusVoice)}</span>
          <button className="q-btn-ghost" type="button" onClick={() => setFocusVoice(null)}>Show all speakers</button>
        </div>
      ) : null}
      {speech.length === 0 ? <p className="q-empty">No transcript is available for this meeting.</p> : null}
      {speech.length > 0 && rows.length === 0 ? <p className="q-empty">Nothing in the transcript matches “{query}”.</p> : null}
      <ol className="q-lines">
        {rows.map((span) => [
          headingBefore.has(span.id) ? (
            <li key={`h:${span.id}`} className="q-line-topic" aria-hidden="false">
              <span className="q-topic-time">{formatMs(headingBefore.get(span.id)!.startMs)}</span>
              <strong>{headingBefore.get(span.id)!.title}</strong>
            </li>
          ) : null,
          span.kind === "untranscribed" ? (
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
            voice={voiceOf(span, ranks)}
            active={span.id === activeId}
            names={names}
            playing={span.id === playingId}
            register={(node) => {
              if (node) lineRefs.current.set(span.id, node);
              else lineRefs.current.delete(span.id);
            }}
            citation={span.id === citation?.span_id ? citation : null}
            onSeek={onSeek}
            onReviseText={onReviseText}
            onReviseSpeaker={onReviseSpeaker}
            focusVoice={focusVoice}
            onFocusVoice={setFocusVoice}
          />
        )])}
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
  voice,
  active,
  names,
  playing,
  register,
  citation,
  onSeek,
  onReviseText,
  onReviseSpeaker,
  focusVoice,
  onFocusVoice,
}: {
  span: Span;
  voice: number;
  active: boolean;
  names: Map<string, string>;
  playing: boolean;
  register: (node: HTMLLIElement | null) => void;
  citation: Citation | null;
  onSeek: (span: Span) => void;
  onReviseText: (span: Span, text: string) => Promise<void>;
  onReviseSpeaker: (span: Span, scope: "span" | "hypothesis", displayName: string) => Promise<void>;
  focusVoice: string | null;
  onFocusVoice: (voiceId: string) => void;
}) {
  const body = span.text.trim() ? span.text : span.raw_text;
  const differs = span.raw_text.trim() && span.raw_text.trim() !== body.trim();
  const [editing, setEditing] = useState(false);
  const voiceId = span.speaker_hypothesis_id;
  const dimmed = Boolean(focusVoice && voiceId !== focusVoice);
  return (
    <li
      ref={register}
      className={["q-line", active ? "is-on" : "", playing ? "is-playing" : "", dimmed ? "is-muted" : ""].filter(Boolean).join(" ")}
      aria-current={playing ? "true" : undefined}
    >
      <div className="q-line-head">
        {span.start_ms !== null ? (
          <button className="q-time" type="button" onClick={() => onSeek(span)} aria-label={`Play from ${formatMs(span.start_ms)}`}>
            {formatMs(span.start_ms)}
          </button>
        ) : null}
        {voiceId ? (
          <VoiceName
            id={voiceId}
            name={names.get(voiceId) || speakerText(span)}
            locked={Boolean(span.speaker_label?.trim())}
            onRename={(_, displayName) => onReviseSpeaker(span, "hypothesis", displayName)}
            className={voice >= 0 ? `q-speaker voice-${voice}` : "q-speaker"}
            trigger="double-click"
            onSelect={() => onFocusVoice(voiceId)}
          />
        ) : (
          <span className="q-speaker">{speakerText(span)}</span>
        )}
        <span className="q-line-tools">
          <IconButton label={editing ? "Close correction" : "Correct this line or its speaker"} pressed={editing} onClick={() => setEditing((value) => !value)}>
            <Pencil size={13} aria-hidden="true" />
          </IconButton>
        </span>
      </div>
      <Highlighted text={body} citation={citation} />
      {differs ? (
        <details className="q-details q-inline-details">
          <summary>Original wording</summary>
          <p className="q-muted">{span.raw_text}</p>
        </details>
      ) : null}
      {editing ? <SpanEdit span={span} onReviseText={onReviseText} onReviseSpeaker={onReviseSpeaker} onClose={() => setEditing(false)} /> : null}
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
  onClose,
}: {
  span: Span;
  onReviseText: (span: Span, text: string) => Promise<void>;
  onReviseSpeaker: (span: Span, scope: "span" | "hypothesis", displayName: string) => Promise<void>;
  onClose: () => void;
}) {
  const area = useRef<HTMLTextAreaElement>(null);
  // Opening the editor puts the cursor in the text, so a keyboard user does not have to Tab past the line to find it.
  useEffect(() => {
    area.current?.focus();
  }, []);
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
    <div
      className="q-edit"
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        // Escape closes the editor and gives focus back to the control that opened it.
        event.stopPropagation();
        const toggle = event.currentTarget.closest(".q-line")?.querySelector<HTMLButtonElement>(".q-line-tools button");
        onClose();
        toggle?.focus();
      }}
    >
      <div className="q-stack">
        <label className="q-label">
          Text
          <textarea ref={area} className="q-area" value={text} onChange={(event) => setText(event.target.value)} />
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
    </div>
  );
}
