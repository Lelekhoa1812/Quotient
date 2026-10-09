"use client";

/**
 * Motivation vs Logic
 * Motivation: The overview answers what a recording said. A reader also asks how it went: who
 * carried it, when it was busy, how topics divided the time, when decisions and questions arose,
 * how much of it could be checked. Those answers are visual, and each should lead back to the moment.
 * Logic: Every chart is computed from the spans, claims and digest (lib/analytics.ts) and shares
 * one focus: pick a voice in any chart and the others dim to it. Clicking any bar, column or dot
 * plays the recording from there. A chart with too little data is not drawn, and the page says
 * what is missing instead of showing a flat or empty shape.
 */
import { useMemo, useState } from "react";
import { ChartCard, DataTable, Donut, EVIDENCE_COLORS, Kpis, Lanes, Legend, Matrix, StackedBars, StackedColumns, StepLines, VOICE_COLORS, voiceColor, type StepSeries } from "@/components/ui/charts";
import {
  EVIDENCE_LABEL,
  bucketWidth,
  buckets,
  claimKinds,
  cumulative,
  evidenceByTopic,
  handoffs,
  kpis,
  minutes,
  momentLanes,
  topicMix,
  voiceStats,
  type EvidenceKey,
} from "@/lib/analytics";
import type { Digest } from "@/lib/digest";
import { durationText, percentText } from "@/lib/present";
import type { Claim, Span } from "@/lib/types";

const KIND_LABEL: Record<string, string> = {
  decision: "Decisions",
  commitment: "Commitments",
  figure: "Figures",
  fact: "Facts",
  question: "Questions",
  risk: "Risks",
  other: "Other",
};

const SERIES_COLORS: Record<string, string> = { questions: "#EF6A63", answers: "#35C486", decisions: "#4F8BFF", actions: "#F2B134" };

export function Insights({ spans, claims, digest, names, onPlay }: { spans: Span[]; claims: Claim[]; digest: Digest | null; names: Map<string, string>; onPlay: (ms: number) => void }) {
  const [focus, setFocus] = useState<string | null>(null);
  const [mode, setMode] = useState<"talk" | "pace">("talk");
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  const voices = useMemo(() => voiceStats(spans, names), [spans, names]);
  const durationMs = useMemo(() => Math.max(0, ...spans.map((span) => span.end_ms ?? 0)), [spans]);
  const colorOf = useMemo(() => new Map(voices.map((voice, index) => [voice.id, voiceColor(index)])), [voices]);
  const chapters = digest?.chapters ?? [];
  const width = bucketWidth(durationMs);
  const cols = useMemo(() => buckets(spans, width, durationMs), [spans, width, durationMs]);
  const kinds = useMemo(() => claimKinds(claims), [claims]);
  const lanes = useMemo(() => (digest ? momentLanes(digest) : []), [digest]);
  const running = useMemo(() => (digest ? cumulative(digest) : []), [digest]);
  const topics = useMemo(() => topicMix(chapters, spans), [chapters, spans]);
  const topicEvidence = useMemo(() => evidenceByTopic(claims, chapters), [claims, chapters]);
  const turnTaking = useMemo(() => handoffs(spans), [spans]);
  const indicators = useMemo(() => kpis(spans, digest, claims, voices), [spans, digest, claims, voices]);

  if (durationMs <= 0 || voices.length === 0) {
    return (
      <section className="q-insights" aria-label="Insights">
        <div className="q-empty-state">
          <h2>No insights yet</h2>
          <p className="q-muted">Charts appear once the recording has been transcribed and its speakers identified.</p>
        </div>
      </section>
    );
  }

  const nameOf = (id: string) => voices.find((voice) => voice.id === id)?.name ?? id;
  const voiceParts = (byVoice: Record<string, number>) =>
    voices.filter((voice) => (byVoice[voice.id] ?? 0) > 0).map((voice) => ({ key: voice.id, label: voice.name, value: byVoice[voice.id], color: colorOf.get(voice.id) ?? VOICE_COLORS[0] }));
  const evidenceKeys: EvidenceKey[] = ["confirmed", "likely", "unchecked", "contradicted"];
  const stepSeries: StepSeries[] = running.map((item) => ({ ...item, color: SERIES_COLORS[item.key] ?? VOICE_COLORS[0] }));
  const matrixVoices = voices.slice(0, 8);
  const cells = matrixVoices.map((from) => matrixVoices.map((to) => turnTaking.find((row) => row.from === from.id && row.to === to.id)?.count ?? 0));
  const exchanges = cells.flat().reduce((sum, value) => sum + value, 0);
  const toggle = (key: string) =>
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <section className="q-insights" aria-label="Insights">
      <header className="q-insights-head">
        <h2>How it went</h2>
        <p className="q-lede">Click anything in a chart to hear that moment. Choose a speaker in a legend to follow just that person across every chart.</p>
      </header>

      <Kpis items={indicators} />

      <div className="q-chart-grid">
        {voices.length >= 2 ? (
          <ChartCard title="Who carried the conversation" question="Share of speaking time by voice.">
            <div className="q-donut-row">
              <Donut
                slices={voices.map((voice) => ({ key: voice.id, label: voice.name, value: voice.ms, color: colorOf.get(voice.id) ?? VOICE_COLORS[0] }))}
                active={focus}
                onActive={setFocus}
                centerTop={percentText(voices[0].share)}
                centerBottom={voices[0].name.length > 18 ? `${voices[0].name.slice(0, 17)}…` : voices[0].name}
                label={`Speaking share: ${voices.map((voice) => `${voice.name} ${percentText(voice.share)}`).join(", ")}`}
              />
              <Legend
                items={voices.map((voice) => ({ key: voice.id, label: voice.name, color: colorOf.get(voice.id) ?? VOICE_COLORS[0], note: `${percentText(voice.share)} · ${voice.turns} ${voice.turns === 1 ? "turn" : "turns"}` }))}
                active={focus}
                onActive={setFocus}
              />
            </div>
          </ChartCard>
        ) : null}

        <ChartCard
          title={mode === "talk" ? "When it was busy" : "How fast people spoke"}
          question={mode === "talk" ? "Speaking time in each stretch, by voice. Alternate shading marks where one topic ends and the next begins." : "Words per minute in each stretch. A dip is a pause or a slow explanation."}
          controls={
            <div className="q-segmented" role="group" aria-label="Chart type">
              <button type="button" className={mode === "talk" ? "is-on" : ""} aria-pressed={mode === "talk"} onClick={() => setMode("talk")}>Talk time</button>
              <button type="button" className={mode === "pace" ? "is-on" : ""} aria-pressed={mode === "pace"} onClick={() => setMode("pace")}>Pace</button>
            </div>
          }
          wide
        >
          <StackedColumns
            columns={cols.map((column) =>
              mode === "talk"
                ? { startMs: column.startMs, endMs: column.endMs, parts: voiceParts(column.byVoice) }
                : { startMs: column.startMs, endMs: column.endMs, parts: [{ key: "pace", label: "Words per minute", value: Math.round((column.words * 60_000) / Math.max(1, column.endMs - column.startMs)), color: VOICE_COLORS[0] }] },
            )}
            durationMs={durationMs}
            active={mode === "talk" ? focus : null}
            format={(value) => (mode === "talk" ? durationText(value) : `${value} words a minute`)}
            onSeek={onPlay}
            bands={chapters.map((chapter) => ({ startMs: chapter.startMs, endMs: chapter.endMs, title: chapter.title }))}
            label={mode === "talk" ? "Talk time over the recording, stacked by voice" : "Words per minute over the recording"}
          />
          {mode === "talk" && voices.length >= 2 ? <Legend items={voices.map((voice) => ({ key: voice.id, label: voice.name, color: colorOf.get(voice.id) ?? VOICE_COLORS[0] }))} active={focus} onActive={setFocus} /> : null}
          <DataTable
            caption={mode === "talk" ? "Talk time per stretch of the recording" : "Words per minute per stretch of the recording"}
            columns={mode === "talk" ? ["Talk time", "Most heard"] : ["Words per minute"]}
            onSeek={onPlay}
            rows={cols.map((column) => {
              const top = Object.entries(column.byVoice).sort((left, right) => right[1] - left[1])[0];
              return {
                atMs: column.startMs,
                cells: mode === "talk"
                  ? [durationText(column.ms), top ? nameOf(top[0]) : "—"]
                  : [Math.round((column.words * 60_000) / Math.max(1, column.endMs - column.startMs))],
              };
            })}
          />
        </ChartCard>

        {topics.length >= 2 ? (
          <ChartCard title="How the time was spent" question="Length of each topic, split by who spoke in it." wide>
            <StackedBars
              rows={topics.map((topic, index) => ({ key: String(index), label: topic.title, startMs: topic.startMs, parts: voiceParts(topic.byVoice) }))}
              active={focus}
              format={(value) => durationText(value)}
              onSeek={onPlay}
              label="Topics by duration and speaker"
            />
          </ChartCard>
        ) : null}

        {lanes.length > 0 ? (
          <ChartCard title="What happened when" question="Decisions, actions, questions, disagreements, risks and figures on the timeline. Hollow dots are unresolved." wide>
            <Lanes lanes={lanes} durationMs={durationMs} onSeek={onPlay} label="Outcomes on the recording timeline" />
            <DataTable
              caption="Decisions, actions, questions, disagreements, risks and figures in time order"
              columns={["Kind", "State", "What"]}
              onSeek={onPlay}
              rows={lanes
                .flatMap((lane) => lane.points.map((point) => ({ atMs: point.startMs, cells: [lane.label, point.tone === "open" ? "Unresolved" : point.tone === "done" ? "Settled" : "", point.text] })))
                .sort((left, right) => left.atMs - right.atMs)}
            />
          </ChartCard>
        ) : null}

        {stepSeries.length > 0 ? (
          <ChartCard
            title="How it built up"
            question="Running totals through the recording. A gap between questions asked and answered is what stayed open."
            wide
            controls={
              <ul className="q-legend is-inline">
                {stepSeries.map((item) => (
                  <li key={item.key}>
                    <button type="button" className={hidden.has(item.key) ? "" : "is-on"} aria-pressed={!hidden.has(item.key)} onClick={() => toggle(item.key)}>
                      <span className="q-swatch" style={{ background: item.color }} aria-hidden="true" />
                      <span className="q-legend-label">{item.label}</span>
                      <span className="q-legend-note">{item.steps[item.steps.length - 1]?.value}</span>
                    </button>
                  </li>
                ))}
              </ul>
            }
          >
            <StepLines series={stepSeries} durationMs={durationMs} hidden={hidden} onSeek={onPlay} label="Cumulative questions, answers, decisions and actions over time" />
            <DataTable
              caption="Each question, answer, decision and action with its running total"
              columns={["Event", "Running total"]}
              onSeek={onPlay}
              rows={stepSeries
                .flatMap((item) => item.steps.map((step) => ({ atMs: step.atMs, cells: [item.label, step.value] })))
                .sort((left, right) => left.atMs - right.atMs)}
            />
          </ChartCard>
        ) : null}

        {kinds.length >= 2 ? (
          <ChartCard title="What was said" question="Kinds of statements the recording contains.">
            <KindsDonut kinds={kinds} />
          </ChartCard>
        ) : null}

        {chapters.length >= 2 && topicEvidence.some((row) => row.counts.confirmed + row.counts.likely + row.counts.unchecked + row.counts.contradicted > 0) ? (
          <ChartCard title="How well each topic is backed up" question="Points per topic by how far they could be checked against the recording. A grey-heavy topic deserves a second look." wide>
            <StackedBars
              rows={topicEvidence.map((row, index) => ({
                key: String(index),
                label: row.title,
                startMs: row.startMs,
                parts: evidenceKeys.map((key) => ({ key, label: EVIDENCE_LABEL[key], value: row.counts[key], color: EVIDENCE_COLORS[key] })),
              }))}
              active={null}
              format={(value) => String(value)}
              onSeek={onPlay}
              label="Points per topic by how far they were checked"
            />
          </ChartCard>
        ) : null}

        {matrixVoices.length >= 2 && exchanges >= 3 ? (
          <ChartCard title="Who answered whom" question="How often one speaker spoke right after another. Shows who drove the exchange." wide>
            <Matrix names={matrixVoices.map((voice) => nameOf(voice.id))} colors={matrixVoices.map((voice) => colorOf.get(voice.id) ?? VOICE_COLORS[0])} cells={cells} label="Turn-taking between voices" />
          </ChartCard>
        ) : null}
      </div>

      <p className="q-faint q-insights-foot">
        Computed from {voices.length} {voices.length === 1 ? "voice" : "voices"} and {minutes(durationMs)} of transcribed speech. Speakers are identified automatically; rename them on the Overview and the charts follow.
      </p>
    </section>
  );
}

function KindsDonut({ kinds }: { kinds: { kind: string; count: number }[] }) {
  const [active, setActive] = useState<string | null>(null);
  const total = kinds.reduce((sum, item) => sum + item.count, 0);
  const slices = kinds.map((item, index) => ({ key: item.kind, label: KIND_LABEL[item.kind] ?? item.kind, value: item.count, color: VOICE_COLORS[index % VOICE_COLORS.length] }));
  return (
    <div className="q-donut-row">
      <Donut slices={slices} active={active} onActive={setActive} centerTop={String(total)} centerBottom="statements" label={`Kinds of statements: ${slices.map((slice) => `${slice.label} ${slice.value}`).join(", ")}`} />
      <Legend items={slices.map((slice) => ({ key: slice.key, label: slice.label, color: slice.color, note: String(slice.value) }))} active={active} onActive={setActive} />
    </div>
  );
}
