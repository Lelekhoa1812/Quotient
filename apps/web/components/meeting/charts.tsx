"use client";

/**
 * Motivation vs Logic
 * Motivation: Charts earn their place by answering a question: how trustworthy
 * are the findings, which topics came up, when was the meeting busy, and where
 * did each topic happen. A chart that restates a table or plots telemetry does
 * not belong here.
 * Logic: lib/insights.ts derives each chart only from stored spans, claims,
 * findings and speaker measures, and returns nothing when the data cannot
 * support a chart. Each chart states its basis, never relies on colour alone
 * (counts are printed), seeks the recording on click, and has a table view.
 */
import { useMemo } from "react";
import { formatMs } from "@/lib/format";
import { buildInsights, type BarRow, type Insight } from "@/lib/insights";
import { countText } from "@/lib/present";
import type { GraphPage, Span } from "@/lib/types";

export function Charts({
  graph,
  unconfirmed,
  onSeekSpan,
  onSeekMs,
}: {
  graph: GraphPage;
  unconfirmed: number;
  onSeekSpan: (span: Span) => void;
  onSeekMs: (ms: number) => void;
}) {
  const insights = useMemo(() => buildInsights(graph, unconfirmed), [graph, unconfirmed]);
  const spansById = useMemo(() => new Map(graph.spans.map((span) => [span.id, span])), [graph.spans]);

  function seekSpan(spanId: string | null | undefined, fallbackMs?: number | null) {
    const span = spanId ? spansById.get(spanId) : undefined;
    if (span) onSeekSpan(span);
    else if (fallbackMs !== null && fallbackMs !== undefined) onSeekMs(fallbackMs);
  }

  return (
    <section className="q-section">
      <div>
        <h2>Insights</h2>
        <p className="q-lede">A few charts that answer common questions about this meeting. Select a bar or dot to hear that moment.</p>
      </div>
      {insights.length === 0 ? (
        <p className="q-empty">There is not enough analysed material yet to chart. Insights appear once the meeting has findings.</p>
      ) : null}
      <div className="q-insights">
        {insights.map((insight) => (
          <article key={insight.id} className="q-insight">
            <header>
              <h3>{insight.title}</h3>
              <p className="q-muted">{insight.question}</p>
            </header>
            <Body insight={insight} onSeek={seekSpan} />
            <p className="q-basis">Based on: {insight.basis}.</p>
            {"note" in insight && insight.note ? <p className="q-muted">{insight.note}</p> : null}
            <TableView insight={insight} />
          </article>
        ))}
      </div>
    </section>
  );
}

function Body({ insight, onSeek }: { insight: Insight; onSeek: (spanId: string | null | undefined, ms?: number | null) => void }) {
  if (insight.kind === "stack") return <Stack rows={insight.rows} />;
  if (insight.kind === "bars") return <Bars rows={insight.rows} />;
  if (insight.kind === "columns") return <Columns rows={insight.rows} unit={insight.unit} onSeek={onSeek} />;
  return <Moments insight={insight} onSeek={onSeek} />;
}

function Stack({ rows }: { rows: { key: string; label: string; value: number; tone: string }[] }) {
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  return (
    <div>
      <div className="q-stack-bar" role="img" aria-label={rows.map((row) => `${row.label}: ${row.value}`).join(", ")}>
        {rows.map((row) => (
          <span key={row.key} className={`q-seg tone-${row.tone}`} style={{ flexGrow: row.value }} title={`${row.label}: ${row.value}`} />
        ))}
      </div>
      <ul className="q-legend">
        {rows.map((row) => (
          <li key={row.key}>
            <span className={`q-swatch tone-${row.tone}`} aria-hidden="true" />
            <span>{row.label}</span>
            <strong>{countText(row.value)}</strong>
            <span className="q-muted">({Math.round((row.value / total) * 100)}%)</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Bars({ rows }: { rows: BarRow[] }) {
  const top = Math.max(...rows.map((row) => row.value), 1);
  return (
    <ul className="q-hbars">
      {rows.map((row) => (
        <li key={row.key}>
          <span className="q-hbar-label">{row.label}</span>
          <span className="q-hbar-track" aria-hidden="true">
            <span className="q-hbar-fill" style={{ width: `${(row.value / top) * 100}%` }} />
          </span>
          <strong className="q-num">{row.display}</strong>
        </li>
      ))}
    </ul>
  );
}

function Columns({
  rows,
  unit,
  onSeek,
}: {
  rows: BarRow[];
  unit: string;
  onSeek: (spanId: string | null | undefined, ms?: number | null) => void;
}) {
  const top = Math.max(...rows.map((row) => row.value), 1);
  return (
    <div>
      <div className="q-cols" role="group" aria-label={`Speech per minute, up to ${top} ${unit}`}>
        {rows.map((row) => (
          <button
            key={row.key}
            type="button"
            className="q-col"
            title={`${row.label}: ${row.display}`}
            aria-label={`${row.label}, ${row.display}. Play from here.`}
            onClick={() => onSeek(row.spanId, row.startMs)}
          >
            <span style={{ height: `${Math.max(row.value > 0 ? 4 : 0, (row.value / top) * 100)}%` }} />
          </button>
        ))}
      </div>
      <div className="q-axis">
        <span>0:00</span>
        <span>{formatMs(((rows.length - 1) / 2) * 60000)}</span>
        <span>{formatMs((rows.length - 1) * 60000)}</span>
      </div>
      <p className="q-muted">Tallest bar: {top} s of speech in one minute.</p>
    </div>
  );
}

function Moments({
  insight,
  onSeek,
}: {
  insight: Extract<Insight, { kind: "moments" }>;
  onSeek: (spanId: string | null | undefined, ms?: number | null) => void;
}) {
  return (
    <div className="q-lanes">
      {insight.lanes.map((lane) => (
        <div key={lane.key} className="q-lane">
          <span className="q-lane-label">{lane.label}</span>
          <div className="q-lane-track">
            {lane.points.map((point) => (
              <button
                key={point.id}
                type="button"
                className="q-dot"
                style={{ left: `${Math.min(99, (point.startMs / insight.durationMs) * 100)}%` }}
                title={`${formatMs(point.startMs)} · ${point.text}`}
                aria-label={`${lane.label} at ${formatMs(point.startMs)}: ${point.text}`}
                onClick={() => onSeek(point.spanId, point.startMs)}
              />
            ))}
          </div>
        </div>
      ))}
      <div className="q-axis q-lane-axis">
        <span>0:00</span>
        <span>{formatMs(insight.durationMs / 2)}</span>
        <span>{formatMs(insight.durationMs)}</span>
      </div>
    </div>
  );
}

function TableView({ insight }: { insight: Insight }) {
  const rows: [string, string][] =
    insight.kind === "moments"
      ? insight.lanes.flatMap((lane) => lane.points.map((point): [string, string] => [`${lane.label} · ${formatMs(point.startMs)}`, point.text]))
      : insight.kind === "stack"
        ? insight.rows.map((row): [string, string] => [row.label, countText(row.value)])
        : insight.rows.map((row): [string, string] => [row.label, row.display]);
  return (
    <details className="q-details">
      <summary>Show as a table</summary>
      <table className="q-table">
        <thead>
          <tr>
            <th scope="col">{insight.kind === "moments" ? "Topic and time" : "Item"}</th>
            <th scope="col">{insight.kind === "moments" ? "Finding" : "Value"}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([left, right], index) => (
            <tr key={`${left}:${index}`}>
              <td>{left}</td>
              <td className={insight.kind === "moments" ? undefined : "q-num"}>{right}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
