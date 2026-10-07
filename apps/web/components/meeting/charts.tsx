"use client";

/**
 * Motivation vs Logic
 * Motivation: The portal chart is the worker's table in one fixed renderer.
 * Logic: Bar length scales the given row values inside that table. The printed
 * value and result are the JSON numbers. The client does not recompute
 * count, sum, mean, min, max, or duration_union.
 */
import { formatTableNumber } from "@/lib/format";
import type { ChartTable } from "@/lib/types";

export function Charts({
  charts,
  spanIds,
  onSeek,
}: {
  charts: ChartTable[];
  spanIds: string[];
  onSeek: (spanId: string) => void;
}) {
  const known = new Set(spanIds);
  return (
    <section className="q-section">
      <div>
        <p className="q-kicker">Charts</p>
        <h2>Tables</h2>
        <p className="q-lede">Each table is the worker result for count, sum, mean, min, max, or duration_union.</p>
      </div>
      {charts.length === 0 ? <p className="q-empty">No chart tables on this graph page.</p> : null}
      {charts.map((chart) => {
        const scale = Math.max(...chart.rows.map((row) => Math.abs(row.value)), 0);
        const heads = chart.columns.length >= 2 ? chart.columns : ["Label", "Value"];
        return (
          <article key={chart.id} className="q-card">
            {chart.aggregation ? <p className="q-meta">{chart.aggregation}</p> : null}
            <h3>{chart.title}</h3>
            {chart.result !== null ? (
              <p><span className="q-meta">Result </span><span className="q-num">{formatTableNumber(chart.result)}</span></p>
            ) : null}
            <div className="q-chart" aria-hidden="true">
              {chart.rows.map((row) => {
                const width = scale > 0 ? (Math.abs(row.value) / scale) * 100 : 0;
                const seek = row.span_id !== null && known.has(row.span_id);
                const body = (
                  <>
                    <div className="q-inline">
                      <span>{row.label}</span>
                      <span className="q-num">{formatTableNumber(row.value)}</span>
                    </div>
                    <div className="q-bar"><span style={{ width: `${width}%` }} /></div>
                  </>
                );
                return seek ? (
                  <button key={row.label} className="q-chart-row" type="button" onClick={() => onSeek(row.span_id ?? "")}>{body}</button>
                ) : (
                  <div key={row.label} className="q-chart-row">{body}</div>
                );
              })}
            </div>
            <table className="q-table">
              <thead>
                <tr>
                  <th>{heads[0]}</th>
                  <th>{heads[1]}</th>
                </tr>
              </thead>
              <tbody>
                {chart.rows.map((row) => {
                  const seek = row.span_id !== null && known.has(row.span_id);
                  return (
                    <tr key={`${chart.id}:${row.label}`}>
                      <td>
                        {seek ? (
                          <button className="q-btn-ghost" type="button" onClick={() => onSeek(row.span_id ?? "")}>{row.label}</button>
                        ) : row.label}
                      </td>
                      <td className="q-num">{formatTableNumber(row.value)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </article>
        );
      })}
    </section>
  );
}
