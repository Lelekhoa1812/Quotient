"use client";

/**
 * Motivation vs Logic
 * Motivation: A synthesis sentence opens its findings, then the cited span,
 * and the player seeks to start_ms. Dissent omissions stay listed. The
 * sentence may be markdown with a mermaid fence in the reading order.
 * Logic: The click records the finding set first. After read_span resolves,
 * the span is attached and seek uses that span's start_ms. Markdown renders
 * the sentence, including a diagram, and the article remains the control.
 */
import type { KeyboardEvent } from "react";
import { Markdown } from "@/components/markdown";
import type { Finding, SynthesisOmission, SynthesisSentence } from "@/lib/types";

function openKey(event: KeyboardEvent, open: () => void) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    open();
  }
}

export function Synthesis({
  sentences,
  omissions,
  findings,
  activeId,
  onOpen,
}: {
  sentences: SynthesisSentence[];
  omissions: SynthesisOmission[];
  findings: Finding[];
  activeId: string | null;
  onOpen: (sentence: SynthesisSentence) => void;
}) {
  return (
    <section className="q-cards">
      <p className="q-kicker">Synthesis</p>
      <h2>Brief</h2>
      <p className="q-lede">Each sentence cites findings. The review queue is excluded from this brief.</p>
      {sentences.length === 0 ? <p className="q-muted">No synthesis sentences on this graph page.</p> : null}
      {sentences.map((sentence) => {
        const cited = findings.filter((finding) => sentence.finding_ids.includes(finding.id));
        return (
          <article
            key={sentence.id}
            className={sentence.id === activeId ? "q-sentence is-on" : "q-sentence"}
            role="button"
            tabIndex={0}
            onClick={() => onOpen(sentence)}
            onKeyDown={(event) => openKey(event, () => onOpen(sentence))}
          >
            <Markdown text={sentence.text} />
            {cited.length > 0 ? (
              <ul className="q-cites">
                {cited.map((finding) => (
                  <li key={finding.id}>
                    <span className="q-meta">{finding.dimension}</span>
                    <span>{finding.text}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </article>
        );
      })}
      <div>
        <p className="q-kicker">Dissent</p>
        <h3>Omissions still listed</h3>
        {omissions.length === 0 ? <p className="q-muted">No dissent omissions on this graph page.</p> : null}
        {omissions.map((omission) => {
          const finding = findings.find((item) => item.id === omission.finding_id);
          return (
            <article key={omission.finding_id} className="q-card">
              <p className="q-kicker">{finding?.dimension ?? "Finding"}</p>
              <p>{finding?.text || omission.finding_id}</p>
              {omission.reason ? <p className="q-muted">{omission.reason}</p> : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
