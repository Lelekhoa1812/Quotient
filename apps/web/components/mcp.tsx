"use client";

/**
 * Motivation vs Logic
 * Motivation: A person has to see whether Quotient is reachable, copy the
 * connection values and the live tool catalog, and hand the partner contract
 * to their own assistant.
 * Logic: The client snapshot supplies phase, session id, path, protocol, and
 * header names. tools/list supplies the catalog. The contract string is
 * already loaded on the server, so the document still renders when the
 * connection is offline. Copy and export are icon-only.
 */
import { useEffect, useState, useSyncExternalStore } from "react";
import { Check, Code, Copy, Download, FileText } from "lucide-react";
import { Markdown } from "@/components/markdown";
import { McpDisconnected, mcp, type Phase, type ToolCatalog } from "@/lib/mcp/client";

type View = "formatted" | "source";

function subscribe(listener: () => void): () => void {
  return mcp.subscribe(listener);
}

function phaseLabel(phase: Phase): "Connected" | "Connecting" | "Offline" {
  if (phase === "connected") return "Connected";
  if (phase === "disconnected") return "Offline";
  return "Connecting";
}

function phaseSentence(phase: Phase): string {
  if (phase === "connected") return "Quotient is reachable.";
  if (phase === "disconnected") return "Quotient is not reachable.";
  return "Checking whether Quotient is reachable.";
}

function originSubscribe(): () => void {
  return () => undefined;
}

function formatTool(tool: ToolCatalog): string {
  const lines = [`tool: ${tool.name}`];
  if (tool.title) lines.push(`title: ${tool.title}`);
  if (tool.description) lines.push(`description: ${tool.description}`);
  if (tool.inputSchema) {
    lines.push("inputSchema:");
    lines.push(JSON.stringify(tool.inputSchema, null, 2));
  }
  return lines.join("\n");
}

export function McpScreen({ contract }: { contract: string }) {
  const phase = useSyncExternalStore(subscribe, () => mcp.phase(), () => "idle" as Phase);
  const sessionId = useSyncExternalStore(subscribe, () => mcp.getSessionId(), () => null);
  const origin = useSyncExternalStore(originSubscribe, () => window.location.origin, () => "");
  const [view, setView] = useState<View>("formatted");
  const [copied, setCopied] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [tools, setTools] = useState<ToolCatalog[]>([]);
  const [toolsNote, setToolsNote] = useState("");
  const [toolsReady, setToolsReady] = useState(false);

  const link = mcp.parameters();
  const portalUrl = origin ? `${origin}${link.endpointPath}` : link.endpointPath;
  const label = phaseLabel(phase);

  useEffect(() => {
    if (mcp.phase() === "idle") {
      void mcp.connect().catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    if (phase !== "connected") {
      setTools([]);
      setToolsNote("");
      setToolsReady(false);
      return;
    }
    let cancel = false;
    setToolsReady(false);
    void mcp.listTools().then(
      (listed) => {
        if (!cancel) {
          setTools(listed);
          setToolsNote("");
          setToolsReady(true);
        }
      },
      (error) => {
        if (cancel) return;
        setTools([]);
        setToolsReady(true);
        setToolsNote(error instanceof McpDisconnected ? "Quotient is offline." : "Tools could not be loaded.");
      },
    );
    return () => {
      cancel = true;
    };
  }, [phase]);

  async function copy(id: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(id);
      window.setTimeout(() => {
        setCopied((current) => (current === id ? null : current));
      }, 1600);
    } catch {
      setMessage("That text could not be copied.");
    }
  }

  function download() {
    const blob = new Blob([contract], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "MCP.md";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function retry() {
    setMessage("");
    mcp.reset();
    void mcp.connect().catch(() => undefined);
  }

  const rows: { id: string; label: string; value: string; note?: string; copyValue: string | null }[] = [
    { id: "url", label: "MCP URL", value: portalUrl, note: "Same origin", copyValue: portalUrl },
    { id: "api", label: "API", value: link.apiUrl, note: "Local default", copyValue: link.apiUrl },
    { id: "protocol", label: "Protocol", value: link.protocolVersion, copyValue: link.protocolVersion },
    { id: "protocol-header", label: "Protocol header", value: link.protocolHeader, copyValue: link.protocolHeader },
    { id: "session-header", label: "Session header", value: link.sessionHeader, copyValue: link.sessionHeader },
    {
      id: "session",
      label: "Session id",
      value: sessionId ?? "Appears after connect",
      copyValue: sessionId,
    },
  ];

  return (
    <main id="main" tabIndex={-1} className="q-portal">
      <header className="q-page-head">
        <h1>MCP</h1>
        <p className="q-lede">Connection values, the live tool list, and the contract to give your assistant.</p>
      </header>

      <section className="q-mcp-connection" aria-labelledby="mcp-connection-heading">
        <div className="q-mcp-status">
          <h2 id="mcp-connection-heading">Connection</h2>
          <p className="q-mcp-phase" role="status">{label}</p>
          <p className="q-muted">{phaseSentence(phase)}</p>
        </div>
        {phase === "disconnected" ? (
          <button className="q-btn-ghost" type="button" onClick={retry}>Try again</button>
        ) : null}
      </section>

      <section className="q-mcp-block" aria-labelledby="mcp-parameters-heading">
        <h2 id="mcp-parameters-heading">Parameters</h2>
        {message ? <p role="alert">{message}</p> : null}
        <dl className="q-mcp-params">
          {rows.map((row) => (
            <div className="q-mcp-row" key={row.id}>
              <dt>{row.label}</dt>
              <dd>
                <span className="q-mcp-copy">
                  <span className={row.copyValue ? "q-mcp-value" : "q-muted"}>{row.value}</span>
                  {row.note ? <span className="q-muted q-mcp-note">{row.note}</span> : null}
                </span>
                <button
                  className="q-icon-btn"
                  type="button"
                  aria-label={copied === row.id ? "Copied" : `Copy ${row.label}`}
                  disabled={row.copyValue === null}
                  onClick={() => {
                    if (row.copyValue) void copy(row.id, row.copyValue);
                  }}
                >
                  {copied === row.id ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
                </button>
              </dd>
            </div>
          ))}
        </dl>
        <p className="q-lede">Paste this contract into your assistant so it can call Quotient.</p>
      </section>

      <section className="q-mcp-block" aria-labelledby="mcp-tools-heading">
        <div className="q-skill-head">
          <h2 id="mcp-tools-heading">Tools</h2>
          <button
            className="q-icon-btn"
            type="button"
            aria-label={copied === "tools" ? "Copied" : "Copy tool list"}
            disabled={tools.length === 0}
            onClick={() => void copy("tools", tools.map(formatTool).join("\n\n"))}
          >
            {copied === "tools" ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
          </button>
        </div>
        {phase === "disconnected" ? (
          <div className="q-mcp-offline">
            <p>Quotient is offline.</p>
            <button className="q-btn-ghost" type="button" onClick={retry}>Try again</button>
          </div>
        ) : null}
        {phase !== "disconnected" && !toolsReady ? <p className="q-muted">Loading tools.</p> : null}
        {phase === "connected" && toolsNote ? (
          <div className="q-mcp-offline">
            <p role="alert">{toolsNote}</p>
            <button className="q-btn-ghost" type="button" onClick={retry}>Try again</button>
          </div>
        ) : null}
        {phase === "connected" && toolsReady && !toolsNote && tools.length === 0 ? <p className="q-muted">No tools are listed.</p> : null}
        {tools.length > 0 ? (
          <div className="q-mcp-tools">
            {tools.map((tool) => (
              <article className="q-mcp-tool" key={tool.name}>
                <div>
                  <h3 className="q-mcp-tool-name">{tool.name}</h3>
                  {tool.title ? <p className="q-meta">{tool.title}</p> : null}
                  {tool.description ? <p>{tool.description}</p> : null}
                </div>
                <button
                  className="q-icon-btn"
                  type="button"
                  aria-label={copied === `tool:${tool.name}` ? "Copied" : `Copy ${tool.name}`}
                  onClick={() => void copy(`tool:${tool.name}`, formatTool(tool))}
                >
                  {copied === `tool:${tool.name}` ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
                </button>
              </article>
            ))}
          </div>
        ) : null}
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
              onClick={() => void copy("contract", contract)}
            >
              {copied === "contract" ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
            </button>
            <button className="q-icon-btn" type="button" aria-label="Export contract" onClick={download}>
              <Download size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
        <div className={view === "source" ? "q-cell is-source q-mcp-doc" : "q-cell q-mcp-doc"} tabIndex={0}>
          {view === "source" ? contract : <Markdown text={contract} />}
        </div>
      </article>
    </main>
  );
}
