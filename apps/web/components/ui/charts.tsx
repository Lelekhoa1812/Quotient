"use client";

/**
 * Motivation vs Logic
 * Motivation: The Insights page needs real charts (donut, stacked columns, step lines, stacked
 * bars, timelines, a matrix) that respond to the reader: hover for the exact number, click to hear
 * the moment, click a legend entry to focus one voice. A charting library would add a large
 * dependency for six simple shapes.
 * Logic: Plain SVG scaled by viewBox, so every chart is responsive and prints. Colours come from
 * one palette shared by speakers and evidence tiers, with a dimmed state for "not the focused
 * series". Tooltips are a small positioned box, not a title attribute, so they work on touch.
 * Charts take already-computed numbers (lib/analytics.ts) and never derive meaning themselves.
 */
import { useId, useState, type ReactNode } from "react";
import { formatMs } from "@/lib/format";

// Deep enough to keep 3:1 against both the white and the near-black page; speakers and evidence tiers use separate sets.
export const VOICE_COLORS = ["#2F6BEE", "#C98500", "#1E9E6A", "#D64545", "#8A5CE0", "#128FA5", "#D9701A", "#6B778C"];
// Seven distinct colours, then one neutral grey for every further voice. Wrapping would give two people the same colour,
// and the extra voices are mostly one person split by the diarizer, so they should not look important.
export const voiceColor = (index: number) => VOICE_COLORS[Math.min(index, VOICE_COLORS.length - 1)];

export const EVIDENCE_COLORS = { confirmed: "#188A5C", likely: "#B7791F", unchecked: "#7A869C", contradicted: "#C0392B" } as const;

const AXIS = "color-mix(in srgb, var(--ink) 55%, transparent)";
const GRID = "color-mix(in srgb, var(--ink) 10%, transparent)";

export function tickTimes(durationMs: number): number[] {
  if (!(durationMs > 0)) return [];
  const steps = [30_000, 60_000, 120_000, 300_000, 600_000, 900_000, 1_800_000];
  const step = steps.find((value) => durationMs / value <= 7) ?? 1_800_000;
  const out: number[] = [];
  for (let at = 0; at <= durationMs; at += step) out.push(at);
  return out;
}

/** A chart's frame: title, the question it answers, optional controls, then the chart. */
export function ChartCard({ title, question, controls, children, wide = false }: { title: string; question: string; controls?: ReactNode; children: ReactNode; wide?: boolean }) {
  return (
    <section className={wide ? "q-chart-card is-wide" : "q-chart-card"} aria-label={title}>
      <header>
        <div>
          <h3>{title}</h3>
          <p className="q-faint">{question}</p>
        </div>
        {controls ? <div className="q-chart-controls">{controls}</div> : null}
      </header>
      {children}
    </section>
  );
}

/** The same numbers as a chart, as a table a keyboard or screen reader can walk. A time cell plays that moment. */
export function DataTable({ columns, rows, onSeek, caption }: { columns: string[]; rows: { atMs: number | null; cells: (string | number)[] }[]; onSeek: (ms: number) => void; caption: string }) {
  if (rows.length === 0) return null;
  return (
    <details className="q-data">
      <summary>Show as a table</summary>
      <div className="q-data-scroll">
        <table>
          <caption className="q-sr">{caption}</caption>
          <thead>
            <tr>
              <th scope="col">Time</th>
              {columns.map((column) => <th key={column} scope="col">{column}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                <th scope="row">
                  {row.atMs === null ? "" : <button type="button" className="q-moment" onClick={() => onSeek(row.atMs as number)} aria-label={`Play from ${formatMs(row.atMs)}`}>{formatMs(row.atMs)}</button>}
                </th>
                {row.cells.map((cell, inner) => <td key={inner}>{cell}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export function Legend({ items, active, onActive }: { items: { key: string; label: string; color: string; note?: string }[]; active: string | null; onActive: (key: string | null) => void }) {
  return (
    <ul className="q-legend">
      {items.map((item) => (
        <li key={item.key}>
          <button
            type="button"
            className={active === item.key ? "is-on" : ""}
            aria-pressed={active === item.key}
            title={active === item.key ? "Show everyone again" : `Focus on ${item.label}`}
            onClick={() => onActive(active === item.key ? null : item.key)}
          >
            <span className="q-swatch" style={{ background: item.color }} aria-hidden="true" />
            <span className="q-legend-label">{item.label}</span>
            {item.note ? <span className="q-legend-note">{item.note}</span> : null}
          </button>
        </li>
      ))}
    </ul>
  );
}

export type Slice = { key: string; label: string; value: number; color: string };

export function Donut({ slices, active, onActive, centerTop, centerBottom, label, interactive = true }: { slices: Slice[]; active: string | null; onActive: (key: string | null) => void; centerTop: string; centerBottom: string; label: string; interactive?: boolean }) {
  // Hover previews a slice; a click pins it (the pin is the shared focus, so it survives the pointer leaving).
  const [hover, setHover] = useState<string | null>(null);
  const shown = interactive ? active ?? hover : null;
  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  const radius = 70;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const hovered = slices.find((slice) => slice.key === shown);
  return (
    <svg className="q-donut" viewBox="0 0 200 200" role="img" aria-label={label}>
      <circle cx="100" cy="100" r={radius} fill="none" stroke={GRID} strokeWidth="26" />
      {total > 0
        ? slices.map((slice) => {
            const length = (slice.value / total) * circumference;
            const dim = shown !== null && shown !== slice.key;
            const element = (
              <circle
                key={slice.key}
                cx="100"
                cy="100"
                r={radius}
                fill="none"
                stroke={slice.color}
                strokeWidth={shown === slice.key ? 30 : 26}
                strokeDasharray={`${Math.max(0, length - 1.5)} ${circumference - Math.max(0, length - 1.5)}`}
                strokeDashoffset={-offset}
                transform="rotate(-90 100 100)"
                opacity={dim ? 0.25 : 1}
                style={{ cursor: interactive ? "pointer" : "default", transition: "opacity 150ms, stroke-width 150ms" }}
                onMouseEnter={interactive ? () => setHover(slice.key) : undefined}
                onMouseLeave={interactive ? () => setHover(null) : undefined}
                onClick={interactive ? () => onActive(active === slice.key ? null : slice.key) : undefined}
              />
            );
            offset += length;
            return element;
          })
        : null}
      <text x="100" y="96" textAnchor="middle" className="q-donut-top">{hovered ? `${Math.round((hovered.value / total) * 100)}%` : centerTop}</text>
      <text x="100" y="116" textAnchor="middle" className="q-donut-bottom">{hovered ? clip(hovered.label, 18) : centerBottom}</text>
    </svg>
  );
}

function clip(text: string, length: number): string {
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}

function Tip({ left, top, children }: { left: number; top: number; children: ReactNode }) {
  return (
    <div className="q-tip" role="status" style={{ left: `${left}%`, top: `${top}px`, transform: left > 60 ? "translateX(-100%)" : undefined }}>
      {children}
    </div>
  );
}

export type Column = { startMs: number; endMs: number; parts: { key: string; label: string; value: number; color: string }[] };

/** Stacked columns over time. `value` is any additive unit; `format` writes it for the tooltip. */
export function StackedColumns({ columns, durationMs, active, format, onSeek, bands = [], height = 190, label }: {
  columns: Column[];
  durationMs: number;
  active: string | null;
  format: (value: number) => string;
  onSeek: (ms: number) => void;
  bands?: { startMs: number; endMs: number; title: string }[];
  height?: number;
  label: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 640;
  const pad = { left: 6, right: 6, top: 8, bottom: 22 };
  const inner = width - pad.left - pad.right;
  const peak = Math.max(1, ...columns.map((column) => column.parts.reduce((sum, part) => sum + part.value, 0)));
  const x = (ms: number) => pad.left + (ms / durationMs) * inner;
  const y = (value: number) => pad.top + (1 - value / peak) * (height - pad.top - pad.bottom);
  const hot = hover === null ? null : columns[hover];
  return (
    <div className="q-chart-wrap">
      <svg className="q-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} onMouseLeave={() => setHover(null)}>
        {bands.map((band, index) => (
          <rect key={index} x={x(band.startMs)} y={pad.top} width={Math.max(0, x(band.endMs) - x(band.startMs))} height={height - pad.top - pad.bottom} fill={index % 2 ? "transparent" : GRID} opacity={0.5} />
        ))}
        <line x1={pad.left} x2={width - pad.right} y1={height - pad.bottom} y2={height - pad.bottom} stroke={GRID} />
        {tickTimes(durationMs).map((at) => (
          <text key={at} x={x(at)} y={height - 6} fontSize="10" fill={AXIS} textAnchor={at === 0 ? "start" : "middle"}>{formatMs(at)}</text>
        ))}
        {columns.map((column, index) => {
          let base = 0;
          const left = x(column.startMs);
          const columnWidth = Math.max(1, x(column.endMs) - left - 1.5);
          return (
            <g key={index} onMouseEnter={() => setHover(index)} onClick={() => onSeek(column.startMs)} style={{ cursor: "pointer" }}>
              <rect x={left} y={pad.top} width={columnWidth} height={height - pad.top - pad.bottom} fill="transparent" />
              {column.parts.map((part) => {
                const top = y(base + part.value);
                const bottom = y(base);
                base += part.value;
                return <rect key={part.key} x={left} y={top} width={columnWidth} height={Math.max(0, bottom - top)} fill={part.color} opacity={active && active !== part.key ? 0.18 : hover === index ? 1 : 0.88} />;
              })}
            </g>
          );
        })}
      </svg>
      {hot ? (
        <Tip left={((x(hot.startMs) + 20) / width) * 100} top={4}>
          <strong>{formatMs(hot.startMs)}–{formatMs(hot.endMs)}</strong>
          {hot.parts.filter((part) => part.value > 0).sort((left, right) => right.value - left.value).slice(0, 5).map((part) => (
            <span key={part.key}><i style={{ background: part.color }} />{part.label} {format(part.value)}</span>
          ))}
          <em>Click to play from here</em>
        </Tip>
      ) : null}
    </div>
  );
}

export type StepSeries = { key: string; label: string; color: string; steps: { atMs: number; value: number }[] };

/** Running totals as step lines, with a crosshair that reads every series at one moment. */
export function StepLines({ series, durationMs, hidden, onSeek, height = 200, label }: { series: StepSeries[]; durationMs: number; hidden: Set<string>; onSeek: (ms: number) => void; height?: number; label: string }) {
  const [at, setAt] = useState<number | null>(null);
  const id = useId();
  const width = 640;
  const pad = { left: 26, right: 8, top: 10, bottom: 22 };
  const shown = series.filter((item) => !hidden.has(item.key));
  const peak = Math.max(1, ...series.map((item) => item.steps[item.steps.length - 1]?.value ?? 0));
  const x = (ms: number) => pad.left + (ms / durationMs) * (width - pad.left - pad.right);
  const y = (value: number) => pad.top + (1 - value / peak) * (height - pad.top - pad.bottom);
  const valueAt = (item: StepSeries, ms: number) => item.steps.filter((step) => step.atMs <= ms).slice(-1)[0]?.value ?? 0;
  const path = (item: StepSeries) => {
    let d = `M ${x(0)} ${y(0)}`;
    let last = 0;
    for (const step of item.steps) {
      d += ` L ${x(step.atMs)} ${y(last)} L ${x(step.atMs)} ${y(step.value)}`;
      last = step.value;
    }
    return `${d} L ${x(durationMs)} ${y(last)}`;
  };
  const ticks = Array.from(new Set([0, Math.ceil(peak / 2), peak]));
  return (
    <div className="q-chart-wrap">
      <svg
        className="q-chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={label}
        onMouseLeave={() => setAt(null)}
        onMouseMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          const fraction = (((event.clientX - box.left) / box.width) * width - pad.left) / (width - pad.left - pad.right);
          setAt(Math.max(0, Math.min(durationMs, fraction * durationMs)));
        }}
        onClick={() => at !== null && onSeek(at)}
        style={{ cursor: "pointer" }}
      >
        {ticks.map((tick) => (
          <g key={`${id}${tick}`}>
            <line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} stroke={GRID} />
            <text x={pad.left - 6} y={y(tick) + 3} fontSize="10" fill={AXIS} textAnchor="end">{tick}</text>
          </g>
        ))}
        {tickTimes(durationMs).map((tickAt) => (
          <text key={tickAt} x={x(tickAt)} y={height - 6} fontSize="10" fill={AXIS} textAnchor={tickAt === 0 ? "start" : "middle"}>{formatMs(tickAt)}</text>
        ))}
        {shown.map((item) => (
          <path key={item.key} d={path(item)} fill="none" stroke={item.color} strokeWidth="2.2" strokeLinejoin="round" />
        ))}
        {at !== null ? <line x1={x(at)} x2={x(at)} y1={pad.top} y2={height - pad.bottom} stroke={AXIS} strokeDasharray="3 3" /> : null}
      </svg>
      {at !== null ? (
        <Tip left={(x(at) / width) * 100} top={4}>
          <strong>{formatMs(at)}</strong>
          {shown.map((item) => (
            <span key={item.key}><i style={{ background: item.color }} />{item.label} {valueAt(item, at)}</span>
          ))}
          <em>Click to play from here</em>
        </Tip>
      ) : null}
    </div>
  );
}

export type BarPart = { key: string; label: string; value: number; color: string };

/** Horizontal stacked bars, one row each, clickable to play the row's start. */
export function StackedBars({ rows, active, format, onSeek, label }: { rows: { key: string; label: string; startMs: number; parts: BarPart[] }[]; active: string | null; format: (value: number) => string; onSeek: (ms: number) => void; label: string }) {
  const peak = Math.max(1, ...rows.map((row) => row.parts.reduce((sum, part) => sum + part.value, 0)));
  return (
    <ul className="q-sbars" aria-label={label}>
      {rows.map((row) => {
        const total = row.parts.reduce((sum, part) => sum + part.value, 0);
        return (
          <li key={row.key}>
            <button type="button" className="q-sbar-label" onClick={() => onSeek(row.startMs)} title={`Play from ${formatMs(row.startMs)}`}>
              <span className="q-time">{formatMs(row.startMs)}</span>
              <span>{row.label}</span>
            </button>
            <span className="q-sbar-track" role="img" aria-label={`${row.label}: ${row.parts.filter((part) => part.value > 0).map((part) => `${part.label} ${format(part.value)}`).join(", ")}`}>
              <span className="q-sbar-fill" style={{ width: `${(total / peak) * 100}%` }}>
                {row.parts.filter((part) => part.value > 0).map((part) => (
                  <span key={part.key} title={`${part.label}: ${format(part.value)}`} style={{ flexGrow: part.value, background: part.color, opacity: active && active !== part.key ? 0.2 : 1 }} />
                ))}
              </span>
            </span>
            <strong className="q-num">{format(total)}</strong>
          </li>
        );
      })}
    </ul>
  );
}

export type Lane = { key: string; label: string; points: { startMs: number; text: string; tone: "plain" | "open" | "done" }[] };

/** One lane per kind of outcome on a shared time axis; hollow = unresolved, filled = settled. */
export function Lanes({ lanes, durationMs, onSeek, label }: { lanes: Lane[]; durationMs: number; onSeek: (ms: number) => void; label: string }) {
  const [hover, setHover] = useState<{ lane: number; point: number } | null>(null);
  const width = 640;
  const left = 96;
  const rowHeight = 30;
  const height = lanes.length * rowHeight + 26;
  const x = (ms: number) => left + (ms / durationMs) * (width - left - 10);
  const hot = hover ? lanes[hover.lane]?.points[hover.point] : null;
  return (
    <div className="q-chart-wrap">
      <svg className="q-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} onMouseLeave={() => setHover(null)}>
        {lanes.map((lane, laneIndex) => {
          const cy = laneIndex * rowHeight + rowHeight / 2 + 4;
          return (
            <g key={lane.key}>
              <line x1={left} x2={width - 10} y1={cy} y2={cy} stroke={GRID} />
              <text x={0} y={cy + 4} fontSize="11" fill={AXIS}>{lane.label}</text>
              {lane.points.map((point, pointIndex) => (
                <circle
                  key={pointIndex}
                  cx={x(point.startMs)}
                  cy={cy}
                  r={hover?.lane === laneIndex && hover.point === pointIndex ? 7 : 5.5}
                  fill={point.tone === "open" ? "var(--bg)" : voiceColor(laneIndex)}
                  stroke={voiceColor(laneIndex)}
                  strokeWidth="2"
                  style={{ cursor: "pointer" }}
                  onMouseEnter={() => setHover({ lane: laneIndex, point: pointIndex })}
                  onClick={() => onSeek(point.startMs)}
                />
              ))}
            </g>
          );
        })}
        {tickTimes(durationMs).map((at) => (
          <text key={at} x={x(at)} y={height - 6} fontSize="10" fill={AXIS} textAnchor={at === 0 ? "start" : "middle"}>{formatMs(at)}</text>
        ))}
      </svg>
      {hot && hover ? (
        <Tip left={(x(hot.startMs) / width) * 100} top={Math.max(0, hover.lane * rowHeight - 6)}>
          <strong>{formatMs(hot.startMs)}</strong>
          <span>{clip(hot.text, 140)}</span>
          <em>{hot.tone === "open" ? "Unresolved" : hot.tone === "done" ? "Settled" : ""} · click to play</em>
        </Tip>
      ) : null}
    </div>
  );
}

/** Square matrix: row = who spoke, column = who spoke next. Colour strength = how often. */
export function Matrix({ names, colors, cells, label }: { names: string[]; colors: string[]; cells: number[][]; label: string }) {
  const peak = Math.max(1, ...cells.flat());
  const [hover, setHover] = useState<[number, number] | null>(null);
  return (
    <div className="q-chart-wrap">
      <div className="q-matrix" aria-hidden="true" style={{ gridTemplateColumns: `minmax(5rem, 9rem) repeat(${names.length}, minmax(1.8rem, 1fr))` }}>
        <span />
        {names.map((name, index) => (
          <span key={index} className="q-matrix-head" title={name}><i style={{ background: colors[index] }} />{index + 1}</span>
        ))}
        {names.map((name, row) => (
          <MatrixRow key={row} name={name} index={row} color={colors[row]} cells={cells[row]} peak={peak} hover={hover} setHover={setHover} />
        ))}
      </div>
      <table className="q-sr">
        <caption>{label}. Each row is who spoke; each column is who spoke next; each cell is how many times.</caption>
        <thead>
          <tr><th scope="col">Spoke first</th>{names.map((name, index) => <th key={index} scope="col">Then {name}</th>)}</tr>
        </thead>
        <tbody>
          {names.map((name, row) => (
            <tr key={row}>
              <th scope="row">{name}</th>
              {cells[row].map((count, column) => <td key={column}>{row === column ? "n/a" : count}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {hover ? (
        <p className="q-matrix-read" role="status">
          After <strong>{names[hover[0]]}</strong>, <strong>{names[hover[1]]}</strong> spoke next <strong>{cells[hover[0]][hover[1]]}</strong> {cells[hover[0]][hover[1]] === 1 ? "time" : "times"}.
        </p>
      ) : (
        <p className="q-matrix-read q-faint">Hover a square to read it. Rows are who spoke; columns are who spoke next.</p>
      )}
    </div>
  );
}

function MatrixRow({ name, index, color, cells, peak, hover, setHover }: { name: string; index: number; color: string; cells: number[]; peak: number; hover: [number, number] | null; setHover: (value: [number, number] | null) => void }) {
  return (
    <>
      <span className="q-matrix-row" title={name}><i style={{ background: color }} />{index + 1}. {clip(name, 22)}</span>
      {cells.map((count, column) => (
        <span
          key={column}
          className={index === column ? "q-matrix-cell is-self" : "q-matrix-cell"}
          style={index === column ? undefined : { background: `color-mix(in srgb, var(--mark) ${Math.round((count / peak) * 100)}%, transparent)`, color: count / peak >= 0.45 ? "#fff" : undefined }}
          onMouseEnter={() => index !== column && setHover([index, column])}
          onMouseLeave={() => setHover(null)}
          data-on={hover?.[0] === index && hover?.[1] === column ? "1" : undefined}
        >
          {index !== column && count > 0 ? count : ""}
        </span>
      ))}
    </>
  );
}

export function Kpis({ items }: { items: { key: string; label: string; value: string; note?: string }[] }) {
  return (
    <ul className="q-kpis" data-count={items.length}>
      {items.map((item) => (
        <li key={item.key}>
          <span className="q-kpi-label">{item.label}</span>
          <strong className="q-kpi-value">{item.value}</strong>
          {item.note ? <span className="q-faint">{item.note}</span> : null}
        </li>
      ))}
    </ul>
  );
}
