"use client";

/**
 * Motivation vs Logic
 * Motivation: Exports are MCP resources on the meeting, not a download API.
 * Logic: Each artifact calls resources/read on its quotient URI and saves the
 * blob the server returned.
 */
import { useState } from "react";
import { Download } from "lucide-react";
import { mcp } from "@/lib/mcp/client";
import type { ExportArtifact } from "@/lib/types";

const CANONICAL: ExportArtifact[] = [
  ["brief.pdf", "PDF"],
  ["captions.vtt", "Captions"],
  ["captions.srt", "Captions SRT"],
  ["burned.mp4", "Captioned video"],
  ["brief.html", "HTML"],
  ["actions.csv", "Actions CSV"],
  ["actions.xlsx", "Actions XLSX"],
  ["graph.json", "JSON graph"],
].map(([name, label]) => ({ name, label, mime_type: "", uri: "" }));

export function Exports({ meetingId, artifacts }: { meetingId: string; artifacts: ExportArtifact[] }) {
  const supplied = new Map(artifacts.map((item) => [item.name, item]));
  const rows = CANONICAL.map((item) => supplied.get(item.name) ?? {
    ...item,
    uri: `quotient://meetings/${meetingId}/exports/${item.name}`,
  });
  for (const extra of artifacts) {
    if (!rows.some((item) => item.name === extra.name)) rows.push(extra);
  }
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");

  async function download(artifact: ExportArtifact) {
    setBusy(artifact.name);
    setMessage("");
    try {
      const body = await mcp.readResource(artifact.uri);
      if (body.href) {
        const anchor = document.createElement("a");
        anchor.href = body.href;
        anchor.download = body.filename;
        anchor.rel = "noopener";
        anchor.click();
      } else if (body.blob) {
        const url = URL.createObjectURL(body.blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = body.filename || artifact.name;
        anchor.click();
        URL.revokeObjectURL(url);
      }
      setMessage(`${artifact.label} ready`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The export did not download");
    } finally {
      setBusy("");
    }
  }

  return (
    <section>
      <h2>Downloads</h2>
      <div className="q-exports">
        {rows.map((artifact) => (
          <button key={artifact.name} className="q-btn" type="button" disabled={busy === artifact.name} onClick={() => void download(artifact)}>
            <Download size={16} aria-hidden="true" />
            {artifact.label}
          </button>
        ))}
      </div>
      {message ? <p role="status">{message}</p> : null}
    </section>
  );
}
