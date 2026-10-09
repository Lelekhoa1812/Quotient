"use client";

/**
 * Motivation vs Logic
 * Motivation: The walkaway is only as good as the statements behind it. A reader who wants to
 * audit it needs two lists: what it rests on (confirmed, and likely with a marker) and what was
 * left out and why, without wading through repeats or a button per row.
 * Logic: Statements are merged by normalised text. "Used" holds confirmed and likely statements;
 * "Left out" holds the rest, grouped by the reason a person would recognise. Each row is the
 * statement, its reason, and a moment (speaker icon) that plays the recording there. Parts of the
 * recording that could not be accounted for are listed last.
 */
import { useState } from "react";
import { Moment } from "@/components/ui/moment";
import { formatTableNumber } from "@/lib/format";
import { readable } from "@/lib/present";
import type { Claim, MeetingStatus, Span, TranscriptGap } from "@/lib/types";

type Group = { claim: Claim; count: number };

const PAGE = 25;

const REASON: Record<string, string> = {
  contradicted: "Contradicted elsewhere in the recording",
  numbers: "A number doesn't match what was said",
  unconfirmed: "Heard, but the meaning couldn't be confirmed",
  "not-found": "Exact words not found in the recording",
};

function reasonOf(claim: Claim): string {
  if (claim.confidence === "contradicted" || claim.status === "contradicted") return "contradicted";
  if (claim.status === "numeric_failed") return "numbers";
  if (claim.citations.length === 0) return "not-found";
  return "unconfirmed";
}

const KIND_ORDER = ["decision", "commitment", "figure", "risk", "question", "fact", "other"] as const;
const KIND_TITLE: Record<(typeof KIND_ORDER)[number], string> = {
  decision: "Decisions",
  commitment: "Commitments",
  figure: "Figures",
  risk: "Risks",
  question: "Questions",
  fact: "Facts",
  other: "Everything else",
};

function kindOf(claim: Claim): (typeof KIND_ORDER)[number] {
  return (KIND_ORDER as readonly string[]).includes(claim.kind) ? (claim.kind as (typeof KIND_ORDER)[number]) : "other";
}

/** Kind first, then time: one stable sort key so a page of rows never splits a group out of order. */
function kindRank(claim: Claim): number {
  return KIND_ORDER.indexOf(kindOf(claim)) * 1e9 + (claim.citations[0]?.start_ms ?? 1e8);
}

function merge(claims: Claim[]): Group[] {
  const groups = new Map<string, Group>();
  for (const claim of claims) {
    const normalized = claim.text.normalize("NFKC").toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
    const key = normalized || claim.id;
    const group = groups.get(key);
    if (group) {
      group.count += 1;
      if (group.claim.citations.length === 0 && claim.citations.length > 0) group.claim = claim;
    } else groups.set(key, { claim, count: 1 });
  }
  return [...groups.values()].sort(
    (left, right) => (left.claim.citations[0]?.start_ms ?? Infinity) - (right.claim.citations[0]?.start_ms ?? Infinity),
  );
}

export function Review({
  claims,
  names = new Map<string, string>(),
  meeting,
  onSeek,
  gaps,
  spans,
  onSeekSpan,
}: {
  claims: Claim[];
  names?: Map<string, string>;
  review: Claim[];
  reviewPresent: boolean;
  meeting: MeetingStatus | null;
  onSeek: (claim: Claim) => void;
  gaps: TranscriptGap[];
  spans: Span[];
  onSeekSpan: (span: Span) => void;
}) {
  const voices = new Set(spans.map((span) => span.speaker_hypothesis_id).filter(Boolean)).size;
  const used = merge(claims.filter((claim) => claim.confidence === "confirmed" || claim.confidence === "likely"));
  const left = merge(claims.filter((claim) => claim.confidence !== "confirmed" && claim.confidence !== "likely"));
  // Open on what the summary rests on; what was left out is one tab away, grouped by why.
  const [tab, setTab] = useState<"left" | "used">(used.length > 0 || left.length === 0 ? "used" : "left");
  const confirmed = used.filter((group) => group.claim.confidence === "confirmed").length;
  const likely = used.length - confirmed;
  const shown = tab === "used" ? used : left;
  void meeting;

  return (
    <section className="q-section" aria-label="Evidence">
      <div>
        <h2>Evidence</h2>
        <p className="q-lede">
          Every point in the overview rests on statements checked against the recording. Here is what was used, and what was left out and why.
        </p>
      </div>
      <p className="q-evidence-tally">
        <span><strong>{formatTableNumber(confirmed)}</strong> confirmed</span>
        <span><strong>{formatTableNumber(likely)}</strong> likely</span>
        <span><strong>{formatTableNumber(left.length)}</strong> left out</span>
        {gaps.length ? <span><strong>{gaps.length}</strong> {gaps.length === 1 ? "part" : "parts"} not checked</span> : null}
      </p>
      <div className="q-segmented" role="group" aria-label="Which statements">
        <button type="button" aria-pressed={tab === "left"} className={tab === "left" ? "is-on" : ""} onClick={() => setTab("left")}>
          Left out ({left.length})
        </button>
        <button type="button" aria-pressed={tab === "used"} className={tab === "used" ? "is-on" : ""} onClick={() => setTab("used")}>
          Used ({used.length})
        </button>
      </div>
      <List key={tab} groups={shown} used={tab === "used"} onSeek={onSeek} text={(value) => readable(value, names, voices)} />
      {gaps.length > 0 ? (
        <details className="q-details">
          <summary>Parts of the recording that were not checked ({gaps.length})</summary>
          <ul className="q-rows">
            {gaps.map((gap) => {
              const first = gap.spanIds.map((spanId) => spans.find((item) => item.id === spanId)).find(Boolean) ?? null;
              return (
                <li key={gap.id} className="q-row">
                  <div className="q-row-main">
                    <p>{first?.text || first?.raw_text || "This part of the recording."}</p>
                    <p className="q-row-meta">{gap.reason || "The analysis could not turn this part into a statement."}</p>
                  </div>
                  {first ? <Moment ms={first.start_ms} onPlay={() => onSeekSpan(first)} /> : null}
                </li>
              );
            })}
          </ul>
        </details>
      ) : null}
    </section>
  );
}

const REASON_ORDER = ["contradicted", "numbers", "unconfirmed", "not-found"] as const;

function Row({ claim, count, used, onSeek, text }: { claim: Claim; count: number; used: boolean; onSeek: (claim: Claim) => void; text: (value: string) => string }) {
  const ms = claim.citations.find((item) => item.start_ms !== null)?.start_ms ?? null;
  return (
    <li className="q-row">
      <div className="q-row-main">
        <p>{claim.text ? text(claim.text) : "Statement without text"}</p>
        <p className="q-row-meta">
          {used ? (claim.confidence === "confirmed" ? "Confirmed" : "Likely: it matches the recording, but one check was not certain") : null}
          {used && count > 1 ? " · " : ""}
          {count > 1 ? `said ${count} times` : ""}
        </p>
      </div>
      {ms !== null ? <Moment ms={ms} onPlay={() => onSeek(claim)} label={text(claim.text)} /> : null}
    </li>
  );
}

function List({ groups, used, onSeek, text }: { groups: Group[]; used: boolean; onSeek: (claim: Claim) => void; text: (value: string) => string }) {
  const [limit, setLimit] = useState(PAGE);
  if (groups.length === 0) {
    return <p className="q-empty">{used ? "No statement could be confirmed yet." : "Nothing was left out."}</p>;
  }
  const more = groups.length > limit ? (
    <button className="q-btn-ghost" type="button" onClick={() => setLimit(limit + PAGE)}>
      Show {Math.min(PAGE, groups.length - limit)} more
    </button>
  ) : null;
  if (used) {
    // Consequential statements first; small talk and scene-setting land in "Other", last. Time order holds inside a group.
    const sorted = [...groups].sort((left, right) => kindRank(left.claim) - kindRank(right.claim));
    const shown = sorted.slice(0, limit);
    return (
      <>
        {KIND_ORDER.map((kind) => {
          const rows = shown.filter((group) => kindOf(group.claim) === kind);
          if (rows.length === 0) return null;
          const total = groups.filter((group) => kindOf(group.claim) === kind).length;
          return (
            <section key={kind} className="q-reason-group" aria-label={KIND_TITLE[kind]}>
              <h3 className="q-reason-title">{KIND_TITLE[kind]} <span className="q-faint">({total})</span></h3>
              <ul className="q-rows">
                {rows.map((group) => <Row key={group.claim.id} {...group} used onSeek={onSeek} text={text} />)}
              </ul>
            </section>
          );
        })}
        {more}
      </>
    );
  }
  // Left out: one heading per reason, so the same sentence is not repeated on every row.
  const shown = groups.slice(0, limit);
  return (
    <>
      {REASON_ORDER.map((reason) => {
        const rows = shown.filter((group) => reasonOf(group.claim) === reason);
        if (rows.length === 0) return null;
        const total = groups.filter((group) => reasonOf(group.claim) === reason).length;
        return (
          <section key={reason} className="q-reason-group" aria-label={REASON[reason]}>
            <h3 className="q-reason-title">{REASON[reason]} <span className="q-faint">({total})</span></h3>
            <ul className="q-rows">
              {rows.map((group) => <Row key={group.claim.id} {...group} used={false} onSeek={onSeek} text={text} />)}
            </ul>
          </section>
        );
      })}
      {more}
    </>
  );
}
