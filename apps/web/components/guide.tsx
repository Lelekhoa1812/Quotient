"use client";

/**
 * Motivation vs Logic
 * Motivation: An external app needs the base URL, the bearer header, and the
 * contract, including the JSON examples, without the API process running.
 * Logic: Connection values are fixed strings the person can copy. The contract
 * string is already loaded on the server. Formatted and source views share it.
 */
import { useState, useSyncExternalStore } from "react";
import { Check, Code, Copy, Download, FileText } from "lucide-react";
import { copyToClipboard } from "@/lib/clipboard";
import { Markdown } from "@/components/markdown";
import { httpMcpUrl, httpsMcpUrl, localHost } from "@/lib/origin";

type View = "formatted" | "source";

function originSubscribe(): () => void {
  return () => undefined;
}

export function ApiScreen({ contract }: { contract: string }) {
  // Bugs vs Fixes
  // Bug: The location snapshot returned a fresh object on every read. React
  // treats a new identity as a store change and re-renders until the page
  // error boundary replaces the contract.
  // Fix: Read the origin and hostname strings. Those values stay stable for
  // this document, which is how the MCP screen subscribes.
  const origin = useSyncExternalStore(originSubscribe, () => window.location.origin, () => "");
  const hostname = useSyncExternalStore(originSubscribe, () => window.location.hostname, () => "");
  const location = hostname ? { hostname, origin } : null;
  const isLocal = !location || localHost(location.hostname);
  const secureBase = httpsMcpUrl(location).replace(/\/mcp$/, "");
  const directBase = httpMcpUrl(location).replace(/\/mcp$/, "");
  const [view, setView] = useState<View>("formatted");
  const [copied, setCopied] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  async function copy(id: string, value: string, label: string) {
    const ok = await copyToClipboard(value);
    if (ok) {
      setCopied(id);
      setMessage(`Copied ${label}.`);
      window.setTimeout(() => {
        setCopied((current) => (current === id ? null : current));
        setMessage("");
      }, 2000);
    } else {
      setMessage("That text could not be copied.");
    }
  }

  function download() {
    const blob = new Blob([contract], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "API.md";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const rows: { id: string; label: string; value: string; note?: string }[] = [
    { id: "base-https", label: "API base (HTTPS)", value: secureBase, note: "Recommended for external apps requiring TLS encryption." },
    { id: "base-http", label: "API base (HTTP)", value: directBase, note: isLocal ? "Local development default." : "Direct ALB origin for existing integrations." },
    { id: "header", label: "Header", value: "Authorization" },
    { id: "bearer", label: "Authorization", value: "Bearer qnt_<key_id>_<secret>", note: "The key from Settings. It does not expire." },
    { id: "on", label: "Streaming on", value: "GET /v1/jobs/{job_id}/events", note: "Set stream to true. Read progress, then one result." },
    { id: "off", label: "Streaming off", value: "GET /v1/jobs/{job_id}", note: "Set stream to false. Poll until the job finishes." },
  ];

  return (
    <main id="main" tabIndex={-1} className="q-portal">
      <header className="q-page-head">
        <h1>API</h1>
        <p className="q-lede">How an external app submits a recording and reads the raw transcript, the analysis, or both.</p>
      </header>
      <p className="q-muted" role="status" aria-live="polite">{message}</p>

      <section className="q-mcp-block" aria-labelledby="api-parameters-heading">
        <h2 id="api-parameters-heading">Parameters</h2>
        <dl className="q-mcp-params">
          {rows.map((row) => (
            <div className="q-mcp-row" key={row.id}>
              <dt>{row.label}</dt>
              <dd>
                <span className="q-mcp-copy">
                  <span className="q-mcp-value">{row.value}</span>
                  {row.note ? <span className="q-muted q-mcp-note">{row.note}</span> : null}
                </span>
                <button
                  className="q-icon-btn"
                  type="button"
                  aria-label={copied === row.id ? "Copied" : `Copy ${row.label}`}
                  onClick={() => void copy(row.id, row.value, row.label)}
                >
                  {copied === row.id ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
                </button>
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <article className="q-skill">
        <div className="q-skill-head">
          <h2>Partner contract</h2>
          <div className="q-skill-actions">
            <button
              className="q-icon-btn"
              type="button"
              aria-pressed={view === "formatted"}
              aria-label="Show formatted"
              onClick={() => setView("formatted")}
            >
              <FileText size={16} aria-hidden="true" />
            </button>
            <button
              className="q-icon-btn"
              type="button"
              aria-pressed={view === "source"}
              aria-label="Show source"
              onClick={() => setView("source")}
            >
              <Code size={16} aria-hidden="true" />
            </button>
            <button
              className="q-icon-btn"
              type="button"
              aria-label={copied === "contract" ? "Copied" : "Copy contract"}
              onClick={() => void copy("contract", contract, "contract")}
            >
              {copied === "contract" ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
            </button>
            <button className="q-icon-btn" type="button" aria-label="Export contract" onClick={download}>
              <Download size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
        <div
          className={view === "source" ? "q-cell is-source q-mcp-doc" : "q-cell q-mcp-doc"}
          tabIndex={0}
          role="region"
          aria-label={view === "source" ? "API contract, source" : "API contract, formatted"}
        >
          {view === "source" ? contract : <Markdown text={contract} />}
        </div>
      </article>
    </main>
  );
}
