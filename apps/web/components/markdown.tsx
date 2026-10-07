"use client";

/**
 * Motivation vs Logic
 * Motivation: Skill text and the partner contract are markdown. Links, pipe
 * tables, and mermaid fences have to render. The source must not become HTML.
 * Logic: Split fences before blank-line blocks. Prose, marks, and link labels
 * stay React text. Only http, https, and mailto become anchors. A mermaid
 * fence mounts the diagram renderer. Other fences stay code.
 */
import { Fragment, type ReactNode } from "react";
import { Diagram } from "@/components/diagram";

type Align = "left" | "center" | "right";

type Block =
  | { kind: "heading"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "paragraph"; lines: string[] }
  | { kind: "table"; header: string[]; align: Align[]; rows: string[][] }
  | { kind: "code"; text: string }
  | { kind: "mermaid"; text: string };

const FENCE = /^[ \t]{0,3}(`{3,}|~{3,})[ \t]*([^`~\n]*)$/;
const MARK = /(\[[^\]]+\]\([^)\s]+\)|`[^`]+`|\*\*[^*]+\*\*|\*[^*\n]+\*)/g;

function safeHref(raw: string): string | null {
  const href = raw.trim();
  if (!href || /[\s<>]/.test(href) || /javascript:/i.test(href)) return null;
  if (/^https?:\/\//i.test(href)) return href;
  if (/^mailto:[^:\s]+$/i.test(href)) return href;
  return null;
}

function inline(text: string, key: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  for (const match of text.matchAll(MARK)) {
    const start = match.index ?? 0;
    if (start > cursor) nodes.push(text.slice(cursor, start));
    const token = match[0];
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token);
    const href = link ? safeHref(link[2]) : null;
    if (link && href) {
      nodes.push(
        <a key={`${key}-a-${start}`} href={href} target="_blank" rel="noreferrer">
          {inline(link[1], `${key}-a-${start}`)}
        </a>,
      );
    } else if (link) nodes.push(token);
    else if (token.startsWith("`")) nodes.push(<code key={`${key}-c-${start}`}>{token.slice(1, -1)}</code>);
    else if (token.startsWith("**")) nodes.push(<strong key={`${key}-b-${start}`}>{token.slice(2, -2)}</strong>);
    else nodes.push(<em key={`${key}-i-${start}`}>{token.slice(1, -1)}</em>);
    cursor = start + token.length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function splitRow(line: string): string[] {
  let text = line.trim();
  if (text.startsWith("|")) text = text.slice(1);
  if (text.endsWith("|")) text = text.slice(0, -1);
  const cells: string[] = [];
  let current = "";
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === "\\" && text[index + 1] === "|") {
      current += "|";
      index += 1;
      continue;
    }
    if (text[index] === "|") {
      cells.push(current.trim());
      current = "";
      continue;
    }
    current += text[index];
  }
  cells.push(current.trim());
  return cells;
}

function alignment(cell: string): Align | null {
  if (!/^:?-+:?$/.test(cell)) return null;
  const left = cell.startsWith(":");
  const right = cell.endsWith(":");
  if (left && right) return "center";
  if (right) return "right";
  return "left";
}

function fit(row: string[], width: number): string[] {
  if (row.length === width) return row;
  if (row.length < width) return [...row, ...Array.from({ length: width - row.length }, () => "")];
  return [...row.slice(0, width - 1), row.slice(width - 1).join(" | ")];
}

function parseTable(lines: string[]): Block | null {
  if (lines.length < 2 || !lines.every((line) => line.trim().startsWith("|"))) return null;
  const header = splitRow(lines[0]);
  const markers = splitRow(lines[1]);
  if (header.length < 2 || markers.length !== header.length) return null;
  const align = markers.map(alignment);
  if (align.some((item) => item === null)) return null;
  return {
    kind: "table",
    header,
    align: align as Align[],
    rows: lines.slice(2).map((line) => fit(splitRow(line), header.length)),
  };
}

function blocks(text: string): Block[] {
  const lines = text.split("\n");
  const found: Block[] = [];
  let index = 0;
  while (index < lines.length) {
    const fence = FENCE.exec(lines[index] ?? "");
    if (fence) {
      const marker = fence[1];
      const info = fence[2].trim().toLowerCase();
      index += 1;
      const body: string[] = [];
      while (index < lines.length && lines[index].trim() !== marker) {
        body.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      const source = body.join("\n").replace(/^\n+|\n+$/g, "");
      found.push(info === "mermaid" ? { kind: "mermaid", text: source } : { kind: "code", text: source });
      continue;
    }
    const paragraph: string[] = [];
    while (index < lines.length && lines[index].trim() && FENCE.exec(lines[index]) === null) {
      paragraph.push(lines[index]);
      index += 1;
    }
    if (paragraph.length > 0) found.push(paragraphBlock(paragraph));
    while (index < lines.length && !lines[index].trim()) index += 1;
  }
  return found;
}

function paragraphBlock(lines: string[]): Block {
  const table = parseTable(lines);
  if (table) return table;
  if (lines.every((line) => /^[-*] /.test(line))) {
    return { kind: "list", ordered: false, items: lines.map((line) => line.slice(2)) };
  }
  if (lines.every((line) => /^\d+\. /.test(line))) {
    return { kind: "list", ordered: true, items: lines.map((line) => line.replace(/^\d+\. /, "")) };
  }
  const heading = /^#{1,3} (.+)$/.exec(lines[0] ?? "");
  if (heading && lines.length === 1) return { kind: "heading", text: heading[1] };
  return { kind: "paragraph", lines };
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="q-md">
      {blocks(text).map((block, index) => {
        if (block.kind === "mermaid") return <Diagram key={index} source={block.text} />;
        if (block.kind === "code") return <pre key={index}><code>{block.text}</code></pre>;
        if (block.kind === "heading") return <h3 key={index}>{inline(block.text, String(index))}</h3>;
        if (block.kind === "table") {
          return (
            <div key={index} className="q-md-table">
              <table>
                <thead>
                  <tr>
                    {block.header.map((cell, cellIndex) => (
                      <th key={cellIndex} scope="col" style={{ textAlign: block.align[cellIndex] }}>
                        {inline(cell, `${index}-h-${cellIndex}`)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex} style={{ textAlign: block.align[cellIndex] }}>
                          {inline(cell, `${index}-${rowIndex}-${cellIndex}`)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (block.kind === "list") {
          const List = block.ordered ? "ol" : "ul";
          return (
            <List key={index}>
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{inline(item, `${index}-${itemIndex}`)}</li>
              ))}
            </List>
          );
        }
        return (
          <p key={index}>
            {block.lines.map((line, lineIndex) => (
              <Fragment key={lineIndex}>
                {lineIndex > 0 ? <br /> : null}
                {inline(line, `${index}-${lineIndex}`)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}
