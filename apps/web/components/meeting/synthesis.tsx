"use client";

/**
 * Motivation vs Logic
 * Motivation: The brief is the headline result. Each sentence has to be
 * traceable to what was said. When the analysis could not confirm everything,
 * the brief still shows what it did confirm and says plainly that it is partial.
 * Logic: A click or Enter on a sentence opens its findings, then the cited
 * span, and the player seeks to start_ms. Dissent omissions are listed as points
 * the brief left out. A needs_review meeting shows its confirmed-only sentences
 * under a "partial brief" notice that links to what was left out.
 */
import { Markdown } from "@/components/markdown";
import { dimensionTitle, isOpenPointTopic } from "@/lib/present";
import type { Finding, SynthesisOmission, SynthesisSentence } from "@/lib/types";

export function Synthesis({
  sentences,
  omissions,
  findings,
  activeId,
  status,
  reviewCount,
  speechLines,
  onOpen,
  onGo,
}: {
  sentences: SynthesisSentence[];
  omissions: SynthesisOmission[];
  findings: Finding[];
  activeId: string | null;
  status: string | null;
  reviewCount: number | null;
  speechLines: number;
  onOpen: (sentence: SynthesisSentence) => void;
  onGo: (view: "review" | "board" | "transcript") => void;
}) {
  const partial = status === "needs_review";
  const failedRun = status === "failed" || status === "cancelled";
  const working = status === "queued" || status === "working";
  return (
    <section className="q-cards">
      <div>
        <h2>Brief</h2>
        <p className="q-lede">
          A short written summary. Select any sentence to see the part of the recording that supports it.
        </p>
      </div>
      {partial ? (
        <article className="q-card q-callout">
          <h3>{sentences.length > 0 ? "This is a partial brief" : "There is no confirmed brief yet"}</h3>
          <p>
            {sentences.length > 0
              ? "It only includes points the analysis confirmed against what was said."
              : "Nothing could be confirmed well enough to put in a written brief. Parts of the analysis may also be incomplete."}
            {reviewCount ? ` ${reviewCount === 1 ? "1 statement is" : `${reviewCount} statements are`} left out because ${reviewCount === 1 ? "it" : "they"} could not be confirmed.` : ""}
          </p>
          <div className="q-inline">
            <button className="q-btn-ghost" type="button" onClick={() => onGo("review")}>See what was left out</button>
            <button className="q-btn-ghost" type="button" onClick={() => onGo("board")}>Browse the key points</button>
          </div>
        </article>
      ) : null}
      {failedRun ? <p className="q-empty">This analysis did not finish, so there is no brief. See “Status” for details.</p> : null}
      {working ? <p className="q-muted">The brief will appear when the analysis finishes.</p> : null}
      {!partial && !working && !failedRun && sentences.length === 0 ? (
        <article className="q-card">
          <h3>Nothing to summarise</h3>
          <p>
            {speechLines === 0
              ? "No speech was found in this recording, so there is nothing to write a brief about."
              : `Only ${speechLines === 1 ? "one short line was" : `${speechLines} short lines were`} found, which is not enough to write a brief.`}
          </p>
          {speechLines > 0 ? (
            <div className="q-inline"><button className="q-btn-ghost" type="button" onClick={() => onGo("transcript")}>Read the transcript</button></div>
          ) : null}
        </article>
      ) : null}
      {sentences.map((sentence) => {
        const cited = findings.filter((finding) => sentence.finding_ids.includes(finding.id));
        return (
          <article key={sentence.id} className={sentence.id === activeId ? "q-sentence is-on" : "q-sentence"}>
            <Markdown text={sentence.text.replace(/^\s*[-*]\s+/, "")} />
            {cited.length > 0 ? (
              <p className="q-meta">
                Based on {cited.length === 1 ? "1 finding" : `${cited.length} findings`}:{" "}
                {[...new Set(cited.map((finding) => dimensionTitle(finding.dimension)))].join(", ")}
              </p>
            ) : null}
            {cited.length > 0 && cited.every((finding) => isOpenPointTopic(finding.dimension)) ? (
              <p className="q-muted">Raised as an open point. It may be answered elsewhere in the recording.</p>
            ) : null}
            <div className="q-inline">
              <button className="q-btn-ghost" type="button" aria-pressed={sentence.id === activeId} onClick={() => onOpen(sentence)}>
                Show where this was said
              </button>
            </div>
          </article>
        );
      })}
      {omissions.length > 0 ? (
        <details className="q-details">
          <summary>Points left out of the brief ({omissions.length})</summary>
          <div className="q-cards">
            {omissions.map((omission) => {
              const finding = findings.find((item) => item.id === omission.finding_id);
              if (!finding) return null;
              return (
                <article key={omission.finding_id} className="q-card">
                  <p className="q-meta">{dimensionTitle(finding.dimension)}</p>
                  <p>{finding.text}</p>
                  {omission.reason ? <p className="q-muted">{omission.reason}</p> : null}
                </article>
              );
            })}
          </div>
        </details>
      ) : null}
    </section>
  );
}
