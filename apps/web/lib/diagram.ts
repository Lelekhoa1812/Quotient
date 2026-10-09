/**
 * Motivation vs Logic
 * Motivation: The diagram renderer has published denial-of-service and CSS-injection flaws in its other chart types (gantt, xychart,
 * radar, architecture, state diagrams with classDef), and the source text is written by a model from a recording a speaker can influence.
 * Logic: One allow-list for what the portal will hand to the renderer: a flowchart or a sequence diagram. Anything else is shown as plain
 * source text instead of being drawn.
 */
const DRAWABLE = new Set(["flowchart", "graph", "sequenceDiagram"]);

export function isDrawable(source: string): boolean {
  return DRAWABLE.has(source.trim().split(/\s+/, 1)[0] ?? "");
}
