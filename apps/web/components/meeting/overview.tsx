"use client";

/**
 * Motivation vs Logic
 * Motivation: The first screen of a meeting answers what someone who was not there needs to know:
 * what it was and what came out of it, what was decided, who does what by when, what is still
 * open, where people disagreed, the figures that matter, and where each topic is. Everything else
 * (unconfirmed statements, coverage) is one tab away, not on this screen.
 * Logic: Render the server-grounded digest in that order. An empty section is not shown. Every
 * item has a moment (speaker icon + time) that plays the recording there. Items resting on
 * "likely" evidence carry a small marker; confirmed items carry none. A meeting analysed before
 * digests existed shows its confirmed brief sentences and offers nothing invented.
 */
import { Check, CircleHelp, Flag, GitCompareArrows, ListChecks, Route, RotateCw, Scale, Sigma, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Diagram } from "@/components/diagram";
import { Markdown } from "@/components/markdown";
import { IconButton, Likely, Moment } from "@/components/ui/moment";
import { ScreenCardView, Storyline } from "@/components/meeting/storyline";
import { UnknownVoiceButton } from "@/components/meeting/unknown-voice";
import { VoiceName } from "@/components/meeting/voices";
import { hasOutcomes, promisedByOwner, type Digest } from "@/lib/digest";
import { formatMs } from "@/lib/format";
import { attachReadings } from "@/lib/readings";
import { buildScreenCards } from "@/lib/screens";
import { buildStoryline, topicIndex } from "@/lib/storyline";
import { durationText, percentText, readable, speakerName } from "@/lib/present";
import type { ActionItem, Claim, ContextUse, IdentityState, MeetingContext, ScreenView, Span, SynthesisSentence, VoiceIdentity } from "@/lib/types";

const TYPE_LABEL: Record<string, string> = {
  meeting: "Meeting",
  presentation: "Presentation",
  lecture: "Lecture",
  discussion: "Discussion",
  interview: "Interview",
  other: "Recording",
};

const DECISION_LABEL = { agreed: "Agreed", tentative: "Tentative", deferred: "Deferred" } as const;

export function Overview({
  digest,
  names,
  spans,
  claims,
  actions,
  synthesis,
  status,
  context = null,
  identities = {},
  screens = [],
  identity = null,
  unknown = [],
  onPlay,
  onAccept,
  onGo,
  onRenameVoice,
  onIdentify,
  onReindex,
}: {
  digest: Digest | null;
  names: Map<string, string>;
  spans: Span[];
  claims: Claim[];
  actions: ActionItem[];
  synthesis: SynthesisSentence[];
  status: string | null;
  /** The reference material the analysis was given; nothing is shown when there is none. */
  context?: MeetingContext | null;
  /** What the analysis decided about each voice (from the picture and from what was said). */
  identities?: Record<string, VoiceIdentity>;
  /** What the picture showed: slides, shared screens, diagrams. */
  screens?: ScreenView[];
  /** Set when a name was saved after the analysis ran, or a reindex failed. */
  identity?: IdentityState | null;
  /** Voices nobody has named. */
  unknown?: string[];
  onPlay: (ms: number) => void;
  onAccept: (actionId: string) => void;
  onGo: (view: "transcript" | "review") => void;
  onRenameVoice: (voiceId: string, displayName: string) => Promise<void>;
  onIdentify?: (voiceId: string) => void;
  onReindex?: () => void;
}) {
  const who = (id: string | null) => (id ? names.get(id) ?? speakerName(null, id) : null);
  const voices = new Set(spans.map((span) => span.speaker_hypothesis_id).filter(Boolean)).size;
  const t = (value: string) => readable(value, names, voices);
  const confirmed = claims.filter((claim) => claim.confidence === "confirmed").length;
  const likely = claims.filter((claim) => claim.confidence === "likely").length;
  const unchecked = claims.length - confirmed - likely;

  const cards = useMemo(() => attachReadings(buildScreenCards(screens), digest?.screenUses ?? []), [screens, digest]);
  const topics = useMemo(() => (digest ? buildStoryline(digest, cards) : []), [digest, cards]);
  const [openTopics, setOpenTopics] = useState<Set<number>>(() => new Set([0]));
  const [reveal, setReveal] = useState<number | null>(null);
  const toggleTopic = useCallback((index: number) => setOpenTopics((current) => {
    const next = new Set(current);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    return next;
  }), []);
  const setAllTopics = useCallback((open: boolean) => setOpenTopics(open ? new Set(topics.map((topic) => topic.index)) : new Set()), [topics]);
  /** Open a topic and bring it into view: the link back from an action, a question or a risk. */
  const goToTopic = useCallback((index: number) => {
    setOpenTopics((current) => new Set(current).add(index));
    setReveal(index);
  }, []);
  useEffect(() => {
    if (reveal === null) return;
    document.getElementById(`topic-${reveal}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
    setReveal(null);
  }, [reveal]);

  if (!digest) {
    const pending = status === "queued" || status === "working";
    const heading = pending ? "The summary is being written" : status === "failed" ? "This analysis did not finish" : status === "cancelled" ? "This analysis was stopped" : "No summary for this meeting yet";
    const body = pending
      ? "It appears here when the analysis finishes."
      : status === "failed"
        ? "Nothing was produced. Upload the recording again to retry."
        : status === "cancelled"
          ? "It was stopped before a summary was written. Upload the recording again to restart it."
          : "This meeting was analysed before summaries, decisions and topics were added, or its summary could not be written. Upload it again to get one.";
    return (
      <section className="q-overview">
        <div className="q-empty-state">
          <h2>{heading}</h2>
          <p className="q-muted">{body}</p>
        </div>
        <ContextUsed context={context} />
        {synthesis.length > 0 ? (
          <Section icon={<ListChecks size={16} />} title="Confirmed points">
            <ul className="q-rows">
              {synthesis.map((sentence) => (
                <li key={sentence.id} className="q-row">
                  <div className="q-row-main"><Markdown text={sentence.text.replace(/^\s*[-*]\s+/, "")} /></div>
                  <Moment ms={sentence.start_ms} onPlay={onPlay} />
                </li>
              ))}
            </ul>
          </Section>
        ) : null}
      </section>
    );
  }

  const unanswered = digest.questions.filter((question) => !question.answered);
  const answered = digest.questions.filter((question) => question.answered);
  const missing = spans.filter((span) => span.kind === "untranscribed" && span.start_ms !== null && span.end_ms !== null);
  const gapNote = missing.length
    ? `Part of the recording (${missing.map((span) => `${formatMs(span.start_ms ?? 0)}–${formatMs(span.end_ms ?? 0)}`).join(", ")}) could not be transcribed, so this summary does not cover it.`
    : "";
  const participation = talkTime(spans, names);
  const locked = new Set(spans.filter((span) => span.speaker_label?.trim() && span.speaker_hypothesis_id).map((span) => span.speaker_hypothesis_id as string));
  const rename = (id: string, name: string) => onRenameVoice(id, name);
  const argued = groupBySpeaker(digest.perspectives);
  /** "From <topic>": the stretch of the meeting an item came from, as a link into the walkthrough. */
  const fromTopic = (ms: number | null) => {
    const index = topicIndex(digest.chapters, ms);
    if (index === null || topics.length === 0) return null;
    return (
      <button type="button" className="q-from-topic" onClick={() => goToTopic(index)} aria-label={`Go to the topic ${digest.chapters[index].title}`}>
        {digest.chapters[index].title}
      </button>
    );
  };
  const storyline = topics.length > 0;
  const stillOpen = unanswered.length + digest.risks.length + digest.disagreements.length;

  const unknownSet = new Set(unknown);
  return (
    <section className="q-overview" aria-label="Meeting overview">
      {identity && !identity.reindexing && (identity.stale || identity.error) ? (
        <div className="q-stale" role="status">
          <RotateCw size={16} aria-hidden="true" />
          <p>
            {identity.error
              ? "The reindex did not finish, so the earlier analysis is kept."
              : "You have changed who spoke since this analysis was written, so the summary, decisions and actions may still use the old names."}
          </p>
          {onReindex ? <button type="button" className="q-btn" onClick={onReindex}>Reindex identity</button> : null}
        </div>
      ) : null}
      <header className="q-hero">
        <p className="q-kicker">{TYPE_LABEL[digest.contentType] ?? "Recording"}</p>
        <h2 className="q-sr">{digest.title || "Summary"}</h2>
        <div className="q-summary-text">
          {digest.summary.map((line, index) => (
            <p key={index}>
              {t(line.text)} <Likely basis={line.basis} />
              <Moment ms={line.startMs} onPlay={onPlay} />
            </p>
          ))}
        </div>
        {digest.outcome ? (
          <p className="q-outcome-line">
            <strong>Where it ended.</strong> {t(digest.outcome.text)}
            <Moment ms={digest.outcome.startMs} onPlay={onPlay} />
          </p>
        ) : null}
        {gapNote ? <p className="q-gap-note" role="note">{gapNote}</p> : null}
        {hasOutcomes(digest) ? (
          <ul className="q-glance" aria-label="At a glance">
            {digest.decisions.length ? <li><a href="#decisions"><strong>{digest.decisions.length}</strong> {digest.decisions.length === 1 ? "decision" : "decisions"}</a></li> : null}
            {digest.actions.length ? <li><a href="#actions"><strong>{digest.actions.length}</strong> {digest.actions.length === 1 ? "action" : "actions"}</a></li> : null}
            {unanswered.length ? <li><a href="#open"><strong>{unanswered.length}</strong> unanswered</a></li> : null}
            {digest.disagreements.length ? <li><a href="#open"><strong>{digest.disagreements.length}</strong> {digest.disagreements.length === 1 ? "disagreement" : "disagreements"}</a></li> : null}
          </ul>
        ) : null}
      </header>

      {digest.decisions.length ? (
        <Section id="decisions" icon={<Scale size={16} />} title="Decisions">
          <ul className="q-rows">
            {digest.decisions.map((decision, index) => (
              <li key={index} className="q-row">
                <span className={`q-pill is-${decision.status}`}>{DECISION_LABEL[decision.status]}</span>
                <div className="q-row-main">
                  <p>{t(decision.statement)} <Likely basis={decision.basis} /></p>
                  {decision.by ? <p className="q-row-meta">Decided by {who(decision.by)}</p> : null}
                </div>
                <Moment ms={decision.startMs} onPlay={onPlay} label={decision.statement} />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {digest.actions.length ? (
        <Section id="actions" icon={<ListChecks size={16} />} title="Action items">
          <ul className="q-rows">
            {digest.actions.map((action, index) => {
              const record = action.actionId ? actions.find((item) => item.id === action.actionId) : undefined;
              const proposed = record ? record.acceptance !== "accepted" : false;
              const agreed = action.agreed || Boolean(record && !proposed);
              const promised = !agreed && promisedByOwner(action, spans);
              return (
                <li key={index} className="q-row">
                  <span
                    className={agreed ? "q-pill is-agreed" : promised ? "q-pill is-promised" : "q-pill"}
                    title={promised ? "The owner said they would do this. Nobody else confirmed it." : undefined}
                  >
                    {agreed ? "Agreed" : promised ? "Promised" : "Suggested"}
                  </span>
                  <div className="q-row-main">
                    <p>{t(action.task)} <Likely basis={action.basis} /></p>
                    <p className="q-row-meta">
                      {who(action.owner) ? <span className="q-chip"><Users size={12} aria-hidden="true" /> {who(action.owner)}</span> : <span className="q-faint">No owner named</span>}
                      {action.due ? <span className="q-chip">Due {action.due}</span> : null}
                      {fromTopic(action.startMs)}
                    </p>
                  </div>
                  {record && proposed ? (
                    <IconButton label={`Confirm action: ${action.task}`} onClick={() => onAccept(record.id)}>
                      <Check size={16} aria-hidden="true" />
                    </IconButton>
                  ) : null}
                  <Moment ms={action.startMs} onPlay={onPlay} label={action.task} />
                </li>
              );
            })}
          </ul>
        </Section>
      ) : null}

      {stillOpen > 0 || (!storyline && digest.questions.length > 0) ? (
        <Section id="open" icon={<CircleHelp size={16} />} title="Still open">
          {unanswered.length ? (
            <>
              <h4 className="q-subhead">Questions nobody settled</h4>
              <ul className="q-rows">
                {unanswered.map((question, index) => (
                  <li key={index} className="q-row">
                    <span className="q-pill is-open">{question.answer ? "Partly answered" : "Open"}</span>
                    <div className="q-row-main">
                      <p>{t(question.question)}</p>
                      {question.answer ? (
                        <p className="q-row-meta">
                          <span>{t(question.answer)}</span>
                          {question.answerMs !== null ? <Moment ms={question.answerMs} onPlay={onPlay} label="the partial reply" /> : null}
                        </p>
                      ) : null}
                      <p className="q-row-meta">
                        {question.askedBy ? <span>Asked by {who(question.askedBy)}</span> : null}
                        {fromTopic(question.startMs)}
                      </p>
                    </div>
                    <Moment ms={question.startMs} onPlay={onPlay} label={question.question} />
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          {digest.disagreements.length ? (
            <>
              <h4 className="q-subhead">Where people disagreed</h4>
              {digest.disagreements.map((item, index) => (
                <div key={index} className="q-dispute">
                  <p className="q-dispute-topic">{t(item.topic)} {fromTopic(item.startMs)}</p>
                  <ul className="q-positions">
                    {item.positions.map((position, inner) => (
                      <li key={inner}>
                        <p className="q-row-meta">{who(position.speaker) ?? "A participant"}</p>
                        <p>{t(position.position)}</p>
                        <Moment ms={position.startMs} onPlay={onPlay} label={position.position} />
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </>
          ) : null}
          {digest.risks.length ? (
            <>
              <h4 className="q-subhead">{digest.contentType === "lecture" || digest.contentType === "presentation" ? "Pitfalls to watch for" : "Risks and concerns"}</h4>
              <ul className="q-rows">
                {digest.risks.map((risk, index) => (
                  <li key={index} className="q-row">
                    <div className="q-row-main">
                      <p><Flag size={14} aria-hidden="true" className="q-inline-icon" /> {t(risk.risk)} <Likely basis={risk.basis} /></p>
                      <p className="q-row-meta">{fromTopic(risk.startMs)}</p>
                    </div>
                    <Moment ms={risk.startMs} onPlay={onPlay} label={risk.risk} />
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          {unanswered.length === 0 && !storyline && answered.length > 0 ? <p className="q-faint">Every question that came up was answered.</p> : null}
        </Section>
      ) : null}

      {storyline ? (
        <Section id="walkthrough" icon={<Route size={16} />} title="Walkthrough by topic">
          <Storyline topics={topics} open={openTopics} onToggle={toggleTopic} onSetAll={setAllTopics} onPlay={onPlay} t={t} />
        </Section>
      ) : (
        <>
          {digest.concepts.length ? (
            <Section icon={<Sigma size={16} />} title="Key ideas explained">
              <dl className="q-concepts">
                {digest.concepts.map((concept, index) => (
                  <div key={index}>
                    <dt>{concept.term} <Likely basis={concept.basis} /> <Moment ms={concept.startMs} onPlay={onPlay} label={concept.term} /></dt>
                    <dd className="q-steps">{t(concept.explanation)}</dd>
                  </div>
                ))}
              </dl>
            </Section>
          ) : null}
          {digest.figures.length ? (
            <Section icon={<Sigma size={16} />} title="Key figures">
              <table className="q-figures">
                <tbody>
                  {digest.figures.map((figure, index) => (
                    <tr key={index}>
                      <th scope="row">{figure.value}</th>
                      <td>{t(figure.what)}</td>
                      <td className="q-cell-end"><Moment ms={figure.startMs} onPlay={onPlay} label={figure.what} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Section>
          ) : null}
          {digest.diagram ? (
            <Section icon={<GitCompareArrows size={16} />} title={digest.diagram.title || "How it fits together"}>
              <Diagram source={digest.diagram.mermaid} />
            </Section>
          ) : null}
          {cards.filter((card) => !card.folded).length > 0 ? (
            <Section icon={<Route size={16} />} title="What was shown">
              <ul className="q-story-rows">
                {cards.filter((card) => !card.folded).map((card) => (
                  <li key={card.id} className="q-story-row is-screen"><ScreenCardView card={card} onPlay={onPlay} /></li>
                ))}
              </ul>
            </Section>
          ) : null}
        </>
      )}

      {participation.length >= 2 || argued.length ? (
        <Section id="people" icon={<Users size={16} />} title="People">
          {participation.length >= 2 ? (
            <>
              <h4 className="q-subhead">Who spoke</h4>
              <ul className="q-hbars is-editable">
                {participation.map((row) => (
                  <li key={row.id}>
                    <div className="q-who-line">
                      <VoiceName id={row.id} name={row.name} locked={locked.has(row.id)} onRename={rename} />
                      {unknownSet.has(row.id) && onIdentify ? <UnknownVoiceButton label={row.name} onOpen={() => onIdentify(row.id)} /> : null}
                      {!locked.has(row.id) && identities[row.id] ? (
                        <span className="q-faint q-from" title={identities[row.id].conflict ? `The ${identities[row.id].source.includes("visual") ? "audio" : "video"} suggested "${identities[row.id].conflict}" instead.` : undefined}>
                          {identities[row.id].source === "audio" ? "named in the talk" : identities[row.id].source === "user" ? "" : "named from the video"}
                          {identities[row.id].conflict ? " · check" : ""}
                        </span>
                      ) : null}
                    </div>
                    <strong className="q-num">{percentText(row.share)}</strong>
                    <span className="q-hbar-track" aria-hidden="true"><span className="q-hbar-fill" style={{ width: `${row.share * 100}%` }} /></span>
                  </li>
                ))}
              </ul>
              <p className="q-faint">Speakers are told apart automatically, using the video when it shows names. Use the pencil to name someone; the name is kept and used everywhere, including the charts.{unknownSet.size > 0 ? " A red marker means nobody could tell who that is; select it to listen and name them." : ""}</p>
            </>
          ) : null}
          {argued.length ? (
            <>
              <h4 className="q-subhead">Who argued what</h4>
              <div className="q-who">
                {argued.map((group) => (
                  <article key={group.speaker ?? "unknown"} className="q-who-card">
                    <header>
                      {group.speaker ? (
                        <VoiceName id={group.speaker} name={who(group.speaker) ?? speakerName(null, group.speaker)} locked={locked.has(group.speaker)} onRename={rename} />
                      ) : (
                        <span className="q-voice-text">A participant</span>
                      )}
                      <span className="q-faint">{group.items.length} {group.items.length === 1 ? "point" : "points"}</span>
                    </header>
                    <ul>
                      {group.items.map((item, index) => (
                        <li key={index}>
                          <p>{t(item.position)}</p>
                          <Moment ms={item.startMs} onPlay={onPlay} label={item.position} />
                        </li>
                      ))}
                    </ul>
                  </article>
                ))}
              </div>
            </>
          ) : null}
        </Section>
      ) : null}

      <ContextUsed context={context} />

      <footer className="q-provenance">
        Built from {confirmed} confirmed{likely ? ` and ${likely} likely` : ""} statements in the recording.
        {unchecked > 0 ? (
          <> {unchecked} others could not be checked and are left out. <button type="button" className="q-link" onClick={() => onGo("review")}>See the evidence</button></>
        ) : null}
      </footer>
    </section>
  );
}

const CONTEXT_STATUS: Record<ContextUse["status"], string> = {
  ready: "Used",
  pending: "Reading",
  skipped: "Skipped",
  failed: "Couldn't read",
};

/**
 * Motivation vs Logic
 * Motivation: Reference material shapes the summary, so a reader should be able to see what the
 * analysis was given and what became of each item, without it crowding the summary.
 * Logic: A quiet disclosure under the summary. The purpose in a sentence, then each item with a status
 * chip and its one-line summary; a skipped or failed item shows its plain reason. No context, no block.
 */
function ContextUsed({ context }: { context: MeetingContext | null }) {
  if (!context || (context.items.length === 0 && !context.purpose)) return null;
  const count = context.items.length;
  return (
    <details className="q-ctx-used">
      <summary>{count > 0 ? `Context used (${count})` : "Context used"}</summary>
      {context.purpose ? <p className="q-ctx-used-purpose">The meeting was described as: {context.purpose}</p> : null}
      {count > 0 ? (
        <ul className="q-ctx-used-list">
          {context.items.map((item, index) => {
            const note = item.status === "skipped" || item.status === "failed" ? item.reason : null;
            return (
              <li key={`${item.name}:${index}`}>
                <span className="q-ctx-used-name">{item.name}</span>
                <span className="q-ctx-chip" data-tone={item.status === "ready" ? "ready" : item.status === "pending" ? "busy" : "bad"}>{CONTEXT_STATUS[item.status]}</span>
                {note ? <span className="q-ctx-used-line">{note}</span> : item.summary ? <span className="q-ctx-used-line">{item.summary}</span> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      <p className="q-faint">Used as reference. None of it is treated as something said in the meeting.</p>
    </details>
  );
}

function Section({ id, icon, title, children }: { id?: string; icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section id={id} className="q-block-section" aria-label={title}>
      <h3 className="q-section-title"><span aria-hidden="true">{icon}</span>{title}</h3>
      {children}
    </section>
  );
}


function talkTime(spans: Span[], names: Map<string, string>): { id: string; name: string; share: number }[] {
  const totals = new Map<string, number>();
  for (const span of spans) {
    if (span.kind !== "speech" || !span.speaker_hypothesis_id || span.start_ms === null || span.end_ms === null) continue;
    totals.set(span.speaker_hypothesis_id, (totals.get(span.speaker_hypothesis_id) ?? 0) + Math.max(0, span.end_ms - span.start_ms));
  }
  const sum = [...totals.values()].reduce((left, right) => left + right, 0);
  if (sum <= 0) return [];
  return [...totals.entries()]
    .map(([id, ms]) => ({ id, name: names.get(id) ?? speakerName(null, id), share: ms / sum }))
    .sort((left, right) => right.share - left.share);
}

function groupBySpeaker(items: Digest["perspectives"]): { speaker: string | null; items: Digest["perspectives"] }[] {
  const groups = new Map<string | null, Digest["perspectives"]>();
  for (const item of items) groups.set(item.speaker, [...(groups.get(item.speaker) ?? []), item]);
  return [...groups.entries()].map(([speaker, rows]) => ({ speaker, items: rows }));
}
