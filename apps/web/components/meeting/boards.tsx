"use client";

/**
 * Motivation vs Logic
 * Motivation: Each topic (decisions, commitments, risks, ...) answers one plain
 * question about the meeting. A topic the recording never touches has to say so
 * rather than look broken.
 * Logic: Tabs list the ten fixed dimensions with their finding counts; the
 * selected tab shows its findings and the evidence behind each. A dimension the
 * worker marked none_in_transcript reads "Not mentioned in the video". Commitments
 * also list their proposed actions. Stored values are unchanged; wording comes
 * from lib/present.ts.
 */
import { useState } from "react";
import { dueText, formatMs, isProposed } from "@/lib/format";
import {
  NOT_MENTIONED,
  OPEN_POINT_NOTE,
  isOpenPointTopic,
  decisionStatusText,
  dimensionQuestion,
  dimensionTitle,
  originText,
  stanceText,
} from "@/lib/present";
import { DIMENSIONS, type ActionItem, type Claim, type Dimension, type Finding, type Span } from "@/lib/types";

export function Boards({
  dimension,
  findings,
  none,
  notEvaluated,
  held,
  unconfirmed: unconfirmedTotal,
  incomplete,
  claims,
  actions,
  spans,
  onDimension,
  onSeekClaim,
  onSeekSpan,
  onAccept,
}: {
  dimension: Dimension;
  findings: Finding[];
  none: Dimension[];
  notEvaluated: Dimension[];
  held: Partial<Record<Dimension, number>>;
  unconfirmed: number;
  incomplete: boolean;
  claims: Claim[];
  actions: ActionItem[];
  spans: Span[];
  onDimension: (dimension: Dimension) => void;
  onSeekClaim: (claim: Claim) => void;
  onSeekSpan: (span: Span) => void;
  onAccept: (actionId: string) => void;
}) {
  const counts = new Map<Dimension, number>();
  for (const finding of findings) {
    if (finding.none_in_transcript) continue;
    counts.set(finding.dimension, (counts.get(finding.dimension) ?? 0) + 1);
  }
  const marked = (item: Dimension) =>
    none.includes(item) || findings.some((finding) => finding.dimension === item && finding.none_in_transcript);
  const rows = findings.filter((finding) => finding.dimension === dimension && !finding.none_in_transcript);
  const unevaluated = notEvaluated.includes(dimension);
  const unconfirmed = held[dimension] ?? 0;
  const absent = marked(dimension) && rows.length === 0 && !unevaluated && unconfirmed === 0;
  const proposed = dimension === "commitment" ? actions : [];

  return (
    <section className="q-section">
      <div>
        <h2>Key points</h2>
        <p className="q-lede">What the meeting covered, by topic. Pick a topic to see what was said and where.</p>
      </div>
      <div
        className="q-tabs"
        role="tablist"
        aria-label="Topics"
        onKeyDown={(event) => {
          const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
          if (!step) return;
          event.preventDefault();
          const next = DIMENSIONS[(DIMENSIONS.indexOf(dimension) + step + DIMENSIONS.length) % DIMENSIONS.length];
          onDimension(next);
          requestAnimationFrame(() => document.getElementById(`tab-${next}`)?.focus());
        }}
      >
        {DIMENSIONS.map((item) => {
          const count = counts.get(item) ?? 0;
          const pending = notEvaluated.includes(item) || (held[item] ?? 0) > 0;
          return (
            <button
              key={item}
              id={`tab-${item}`}
              type="button"
              role="tab"
              aria-selected={item === dimension}
              aria-controls="topic-panel"
              tabIndex={item === dimension ? 0 : -1}
              className={item === dimension ? "q-tab is-on" : "q-tab"}
              onClick={() => onDimension(item)}
            >
              {dimensionTitle(item)}
              <span
                className={count > 0 ? "q-tab-count" : "q-tab-count is-none"}
                aria-label={count > 0 ? `${count} points` : pending ? "not confirmed yet" : "none"}
              >
                {count > 0 ? count : pending ? "?" : "–"}
              </span>
            </button>
          );
        })}
      </div>
      <div id="topic-panel" role="tabpanel" aria-labelledby={`tab-${dimension}`} className="q-cards">
        <p className="q-kicker">{dimensionQuestion(dimension)}</p>
        {isOpenPointTopic(dimension) && rows.length > 0 ? <p className="q-muted">{OPEN_POINT_NOTE}</p> : null}
        {absent && !unconfirmedTotal && !incomplete ? <p className="q-empty">{NOT_MENTIONED}.</p> : null}
        {absent && (unconfirmedTotal > 0 || incomplete) ? (
          <p className="q-empty">
            No confirmed points on this topic.
            {unconfirmedTotal > 0 ? ` ${unconfirmedTotal} statements in this meeting could not be confirmed yet, so something may be missing. See “To check”.` : ""}
            {incomplete ? " Part of the recording could not be analysed." : ""}
          </p>
        ) : null}
        {unevaluated ? <p className="q-empty">This topic could not be analysed. Run the analysis again to check it.</p> : null}
        {!unevaluated && unconfirmed > 0 ? (
          <p className="q-empty">
            {unconfirmed === 1 ? "1 point on this topic is" : `${unconfirmed} points on this topic are`} not confirmed yet, so
            {unconfirmed === 1 ? " it is" : " they are"} not shown here. See “To check”.
          </p>
        ) : null}
        {!absent && !unevaluated && unconfirmed === 0 && rows.length === 0 && proposed.length === 0 ? (
          <p className="q-empty">Nothing has been recorded for this topic yet.</p>
        ) : null}
        {rows.map((finding) => (
          <article key={finding.id} className={finding.stance === "conflicts" ? "q-card is-conflict" : "q-card"}>
            {finding.stance !== "supports" ? <p className="q-meta">{stanceText(finding.stance)}</p> : null}
            <p>{finding.text}</p>
            {finding.claim_ids.map((claimId) => {
              const claim = claims.find((item) => item.id === claimId);
              if (!claim) return null;
              const quote = claim.citations.find((item) => item.quote)?.quote;
              return (
                <button key={claim.id} className="q-evidence" type="button" onClick={() => onSeekClaim(claim)}>
                  <span className="q-evidence-label">Heard in the recording</span>
                  {quote ? <q>{quote}</q> : <span>{claim.text}</span>}
                  {claim.kind === "decision" ? <span className="q-badge">{decisionStatusText(claim.decision_status)}</span> : null}
                </button>
              );
            })}
          </article>
        ))}
        {dimension === "commitment" ? <Actions actions={actions} spans={spans} onSeekSpan={onSeekSpan} onAccept={onAccept} /> : null}
      </div>
    </section>
  );
}

function Actions({
  actions,
  spans,
  onSeekSpan,
  onAccept,
}: {
  actions: ActionItem[];
  spans: Span[];
  onSeekSpan: (span: Span) => void;
  onAccept: (actionId: string) => void;
}) {
  const [busy, setBusy] = useState("");
  if (actions.length === 0) return null;
  return (
    <div className="q-cards">
      <h3>Follow-up actions</h3>
      {actions.map((action) => {
        const human = action.origin === "human";
        const ownerSpan = action.owner_span_id ? spans.find((span) => span.id === action.owner_span_id) ?? null : null;
        const due = dueText(action);
        return (
          <article key={action.id} className={human ? "q-card is-human" : "q-card"}>
            <p>{action.statement}</p>
            <p className="q-muted">
              {ownerSpan ? "Who takes it on: see what was said below" : "Nobody was named to take it on"}
              {" · "}
              {due ? `Due: ${due}` : "No deadline mentioned"}
            </p>
            {ownerSpan ? (
              <blockquote className="q-quote-block">
                <q>{(ownerSpan.text || ownerSpan.raw_text).trim().slice(0, 140)}{(ownerSpan.text || ownerSpan.raw_text).trim().length > 140 ? "…" : ""}</q>
                {ownerSpan.start_ms !== null ? <span className="q-muted"> · {formatMs(ownerSpan.start_ms)}</span> : null}
              </blockquote>
            ) : null}
            <div className="q-inline">
              <span className="q-state" data-state={isProposed(action) ? "proposed" : "accepted"}>
                {isProposed(action) ? "Needs your confirmation" : human ? "Confirmed by a person" : "Owner stated in the recording"}
              </span>
              <span className="q-muted">{originText(action.origin)}</span>
            </div>
            <div className="q-inline">
              {ownerSpan ? (
                <button className="q-btn-ghost" type="button" onClick={() => onSeekSpan(ownerSpan)}>Hear this moment</button>
              ) : null}
              {isProposed(action) ? (
                <button
                  className="q-btn"
                  type="button"
                  disabled={busy === action.id}
                  onClick={() => {
                    setBusy(action.id);
                    onAccept(action.id);
                  }}
                >
                  {busy === action.id ? "Confirming…" : "Confirm action"}
                </button>
              ) : null}
            </div>
          </article>
        );
      })}
    </div>
  );
}
