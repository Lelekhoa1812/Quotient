"use client";

/**
 * Motivation vs Logic
 * Motivation: A reader who missed the meeting needs to see what was shown, asked and explained in the order it happened, with the screen
 * next to what was being said, not eleven separate lists. Raw screen text is evidence, not the story.
 * Logic: One block per topic (chapter). Inside it, in time order: screens as cards. A card leads with the reading of what that
 * screen was for in the talk, then the figures copied off it, then a "Demo sample" tag where the screen said so. A sentence marked
 * as a difference is where the screen and the talk state different facts. The cleaned screen text and the raw reading sit behind
 * disclosures. Answered questions, ideas, figures and the diagram follow in time. Open questions, actions and risks are not repeated
 * here; each topic only counts them and the sections above link back to it.
 */
import { ChevronDown, ChevronRight, MonitorPlay } from "lucide-react";
import { Diagram } from "@/components/diagram";
import { Likely, Moment } from "@/components/ui/moment";
import { formatMs } from "@/lib/format";
import { durationText } from "@/lib/present";
import type { ScreenCard } from "@/lib/screens";
import type { StoryRow, Topic } from "@/lib/storyline";

const KIND_LABEL: Record<string, string> = {
  slide: "Slide",
  screen_share: "Shared screen",
  diagram: "Diagram",
  whiteboard: "Whiteboard",
  document: "Document",
  spreadsheet: "Spreadsheet",
  code: "Code",
  ui: "App page",
  chart: "Chart",
  other: "On screen",
};

const MAX_LINES = 14;

function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

function counts(topic: Topic): string {
  const parts: string[] = [];
  if (topic.counts.screens) parts.push(plural(topic.counts.screens, "screen"));
  if (topic.counts.answered) parts.push(`${topic.counts.answered} answered`);
  if (topic.counts.open) parts.push(`${topic.counts.open} open`);
  if (topic.counts.actions) parts.push(plural(topic.counts.actions, "action"));
  if (topic.counts.ideas) parts.push(plural(topic.counts.ideas, "idea"));
  return parts.join(" · ");
}

export function Storyline({
  topics,
  open,
  onToggle,
  onSetAll,
  onPlay,
  t,
}: {
  topics: Topic[];
  open: Set<number>;
  onToggle: (index: number) => void;
  onSetAll: (open: boolean) => void;
  onPlay: (ms: number) => void;
  /** Replaces speaker ids in model text with the names the reader sees. */
  t: (value: string) => string;
}) {
  const screens = topics.reduce((sum, topic) => sum + topic.counts.screens, 0);
  const allOpen = topics.every((topic) => open.has(topic.index));
  return (
    <div className="q-story">
      <div className="q-story-bar">
        <p className="q-faint">
          {plural(topics.length, "topic")}
          {screens ? ` · ${plural(screens, "screen")} shown` : ""}
        </p>
        <button type="button" className="q-link" onClick={() => onSetAll(!allOpen)}>
          {allOpen ? "Collapse all" : "Expand all"}
        </button>
      </div>
      <ol className="q-story-topics">
        {topics.map((topic) => {
          const isOpen = open.has(topic.index);
          const panel = `topic-panel-${topic.index}`;
          return (
            <li key={topic.index} id={`topic-${topic.index}`} className={isOpen ? "q-story-topic is-open" : "q-story-topic"}>
              <h4 className="q-story-head">
                <button type="button" className="q-story-toggle" aria-expanded={isOpen} aria-controls={panel} onClick={() => onToggle(topic.index)}>
                  <span className="q-story-chevron" aria-hidden="true">{isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</span>
                  <span className="q-topic-time">{formatMs(topic.chapter.startMs)}</span>
                  <span className="q-story-title">
                    <strong>{topic.chapter.title}</strong>
                    <span className="q-story-counts">{counts(topic)}</span>
                  </span>
                  <span className="q-topic-len">{durationText(topic.chapter.endMs - topic.chapter.startMs)}</span>
                </button>
              </h4>
              <div id={panel} hidden={!isOpen} className="q-story-body">
                {topic.chapter.gist ? <p className="q-story-gist">{t(topic.chapter.gist)}</p> : null}
                <div className="q-story-play">
                  <Moment ms={topic.chapter.startMs} onPlay={onPlay} label={`topic ${topic.chapter.title}`} />
                  <span className="q-faint">Play this topic</span>
                </div>
                {topic.rows.length > 0 ? (
                  <ul className="q-story-rows">
                    {topic.rows.map((row, index) => (
                      <li key={index} className={`q-story-row is-${row.kind}`}>
                        <Row row={row} onPlay={onPlay} t={t} />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="q-faint">Nothing was shown or explained in this stretch beyond what the summary says.</p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Row({ row, onPlay, t }: { row: StoryRow; onPlay: (ms: number) => void; t: (value: string) => string }) {
  switch (row.kind) {
    case "screen":
      return <ScreenCardView card={row.card} onPlay={onPlay} />;
    case "folded":
      return (
        <p className="q-story-quiet">
          <MonitorPlay size={14} aria-hidden="true" />
          {row.cards.length === 1 ? "A screen with no readable content" : `${row.cards.length} screens with no readable content`}
          <Moment ms={row.ms} onPlay={onPlay} />
        </p>
      );
    case "answer":
      return (
        <div className="q-qa">
          <p><span className="q-story-tag">Asked</span> {t(row.question.question)} <Moment ms={row.question.startMs} onPlay={onPlay} label={row.question.question} /></p>
          {row.question.answer ? (
            <p><span className="q-story-tag is-answer">Answered</span> {t(row.question.answer)} {row.question.answerMs !== null ? <Moment ms={row.question.answerMs} onPlay={onPlay} label="the answer" /> : null}</p>
          ) : null}
        </div>
      );
    case "idea":
      return (
        <div>
          <p className="q-story-line"><span className="q-story-tag is-idea">Idea</span> <strong>{row.concept.term}</strong> <Likely basis={row.concept.basis} /> <Moment ms={row.concept.startMs} onPlay={onPlay} label={row.concept.term} /></p>
          <p className="q-story-text">{t(row.concept.explanation)}</p>
        </div>
      );
    case "figure":
      return (
        <p className="q-story-line">
          <span className="q-story-tag is-figure">Figure</span> <strong className="q-num">{row.figure.value}</strong> {t(row.figure.what)}
          <Moment ms={row.figure.startMs} onPlay={onPlay} label={row.figure.what} />
        </p>
      );
    case "diagram":
      return (
        <div>
          <p className="q-story-line"><span className="q-story-tag is-idea">Diagram</span> {row.diagram.title || "How it fits together"}</p>
          <Diagram source={row.diagram.mermaid} />
        </div>
      );
    default:
      return null;
  }
}

function range(card: ScreenCard): string {
  return card.endMs - card.startMs > 4000 ? `${formatMs(card.startMs)}–${formatMs(card.endMs)}` : formatMs(card.startMs);
}

/** One screen: a plain title and what it showed, never the raw reading by default. */
export function ScreenCardView({ card, onPlay }: { card: ScreenCard; onPlay: (ms: number) => void }) {
  const shown = card.lines.slice(0, MAX_LINES);
  const hidden = card.lines.length - shown.length;
  return (
    <article className="q-screen-card" aria-label={`Shown: ${card.title || "a screen"}, ${range(card)}`}>
      <header className="q-screen-card-head">
        <span className="q-story-tag is-shown"><MonitorPlay size={12} aria-hidden="true" /> {KIND_LABEL[card.kind] ?? "On screen"}</span>
        <strong>{card.title || "Untitled screen"}</strong>
        <span className="q-screen-range">
          <Moment ms={card.startMs} onPlay={onPlay} label={card.title || "the screen"} />
          <span className="q-faint">{range(card)}</span>
        </span>
      </header>
      {card.reading ? <p className="q-screen-reading">{card.reading}</p> : null}
      {card.differs ? (
        <p className="q-screen-differs"><span className="q-story-tag">Screen and talk differ</span> {card.differs}</p>
      ) : null}
      {card.highlights.length > 0 ? (
        <ul className="q-hl-list" aria-label="Figures on the screen">
          {card.highlights.map((item) => (
            <li key={item.label} className="q-hl">
              <span className="q-hl-label">{item.label}</span>
              <strong className="q-num">{item.value}</strong>
              {item.sample ? <span className="q-hl-flag">demo sample</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {shown.length > 0 ? (
        <details className="q-screen-more">
          <summary>Screen text</summary>
          <ul className="q-screen-lines">
            {shown.map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ul>
          {hidden > 0 || card.moreRows > 0 ? (
            <p className="q-faint">
              {[hidden > 0 ? plural(hidden, "more line") : "", card.moreRows > 0 ? plural(card.moreRows, "more table row") : ""].filter(Boolean).join(" and ")} not shown.
            </p>
          ) : null}
          <details className="q-screen-raw">
            <summary>As read from the video</summary>
            <p className="q-faint">A model read this from the frames, so it can be garbled. Check anything that matters against the recording.</p>
            <pre className="q-screen-text">{card.raw}</pre>
            {card.layout.trim() ? <pre className="q-screen-text">{card.layout}</pre> : null}
          </details>
        </details>
      ) : null}
    </article>
  );
}
