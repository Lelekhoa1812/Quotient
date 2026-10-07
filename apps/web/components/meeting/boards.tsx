"use client";

/**
 * Motivation vs Logic
 * Motivation: Each lens has its own board, including a dimension the lens
 * marked none_in_transcript. Commitment boards carry proposed actions.
 * Logic: Ten fixed dimensions stay mounted. A null owner renders "not stated".
 * Human-origin actions stay visually distinct from model proposals.
 */
import { dueText, isProposed, ownerText, statusLabel } from "@/lib/format";
import { DIMENSIONS, DIMENSION_LABEL, type ActionItem, type Claim, type Dimension, type Finding, type Span } from "@/lib/types";

export function Boards({
  dimension,
  findings,
  none,
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
  claims: Claim[];
  actions: ActionItem[];
  spans: Span[];
  onDimension: (dimension: Dimension) => void;
  onSeekClaim: (claim: Claim) => void;
  onSeekSpan: (span: Span) => void;
  onAccept: (actionId: string) => void;
}) {
  return (
    <section className="q-section">
      <div>
        <p className="q-kicker">Boards</p>
        <h2>Ten lenses</h2>
        <p className="q-lede">Every lens stays on this page. An empty lens is none_in_transcript.</p>
      </div>
      <div className="q-board-grid">
        {DIMENSIONS.map((item) => (
          <Lens
            key={item}
            dimension={item}
            current={item === dimension}
            findings={findings}
            none={none}
            claims={claims}
            actions={item === "commitment" ? actions : []}
            spans={spans}
            onDimension={onDimension}
            onSeekClaim={onSeekClaim}
            onSeekSpan={onSeekSpan}
            onAccept={onAccept}
          />
        ))}
      </div>
    </section>
  );
}

function Lens({
  dimension,
  current,
  findings,
  none,
  claims,
  actions,
  spans,
  onDimension,
  onSeekClaim,
  onSeekSpan,
  onAccept,
}: {
  dimension: Dimension;
  current: boolean;
  findings: Finding[];
  none: Dimension[];
  claims: Claim[];
  actions: ActionItem[];
  spans: Span[];
  onDimension: (dimension: Dimension) => void;
  onSeekClaim: (claim: Claim) => void;
  onSeekSpan: (span: Span) => void;
  onAccept: (actionId: string) => void;
}) {
  const rows = findings.filter((finding) => finding.dimension === dimension && !finding.none_in_transcript);
  const marked = none.includes(dimension) || findings.some((finding) => finding.dimension === dimension && finding.none_in_transcript);
  return (
    <section id={`lens-${dimension}`} className={current ? "q-lens is-current" : "q-lens"}>
      <button className="q-btn-ghost" type="button" onClick={() => onDimension(dimension)}>
        {DIMENSION_LABEL[dimension]}
      </button>
      {marked ? (
        <div className="q-empty">
          <p>Nothing in the transcript supports this board.</p>
        </div>
      ) : null}
      {rows.length === 0 && !marked ? <p className="q-empty">Nothing on this board yet.</p> : null}
      {rows.map((finding) => (
        <article key={finding.id} className={finding.stance === "conflicts" ? "q-card is-conflict" : "q-card"}>
          <p className="q-meta">{statusLabel(finding.stance)}</p>
          <p>{finding.text}</p>
          {finding.claim_ids.map((claimId) => {
            const claim = claims.find((item) => item.id === claimId);
            if (!claim) return <p key={claimId} className="q-muted">{claimId}</p>;
            const quote = claim.citations.find((item) => item.quote)?.quote;
            return (
              <button key={claim.id} className="q-btn-ghost" type="button" onClick={() => onSeekClaim(claim)}>
                {claim.text || claim.id}
                {quote ? <mark>{quote}</mark> : null}
                {claim.coarse ? <span className="q-badge">Coarse</span> : null}
                {claim.overlap ? <span className="q-badge">Overlap</span> : null}
                {claim.decision_status === null && claim.kind === "decision" ? <span>not stated</span> : null}
                {claim.decision_status ? <span className="q-badge">{claim.decision_status}</span> : null}
              </button>
            );
          })}
        </article>
      ))}
      {dimension === "commitment" ? <Actions actions={actions} spans={spans} onSeekSpan={onSeekSpan} onAccept={onAccept} /> : null}
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
  return (
    <div className="q-cards">
      <h3>Actions</h3>
      {actions.length === 0 ? <p className="q-empty">No actions on this graph page.</p> : null}
      {actions.map((action) => {
        const human = action.origin === "human";
        const ownerSpan = action.owner_span_id ? spans.find((span) => span.id === action.owner_span_id) ?? null : null;
        return (
          <article key={action.id} className={human ? "q-card is-human" : "q-card"}>
            <p>{action.statement}</p>
            <p>Owner: {ownerText(action, spans)}</p>
            {dueText(action) ? <p>{dueText(action)}</p> : null}
            <div className="q-inline">
              <span className="q-state" data-state={isProposed(action) ? "proposed" : "accepted"}>
                {isProposed(action) ? "Proposed" : "Accepted"}
              </span>
              {human ? <span className="q-badge">Human record</span> : null}
            </div>
            {human ? <p className="q-muted">Not regenerated.</p> : null}
            {ownerSpan ? (
              <button className="q-btn-ghost" type="button" onClick={() => onSeekSpan(ownerSpan)}>Open owner span</button>
            ) : null}
            {isProposed(action) ? (
              <button className="q-btn" type="button" onClick={() => onAccept(action.id)}>Accept</button>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}
