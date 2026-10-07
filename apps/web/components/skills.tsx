"use client";

/**
 * Motivation vs Logic
 * Motivation: Assistants need the live skill text, and a person needs to copy
 * or export it without reading protocol names.
 * Logic: prompts/list supplies the catalog. prompts/get supplies the body.
 * The cell toggles formatted and source views. Copy and export are icon-only.
 */
import { useEffect, useState } from "react";
import { Check, Code, Copy, Download, FileText } from "lucide-react";
import { Markdown } from "@/components/markdown";
import { McpDisconnected, mcp, type SkillSummary } from "@/lib/mcp/client";

type Skill = SkillSummary & { text: string; view: "formatted" | "source"; copied: boolean };

const TIPS = [
  "Start with a recording. Slides and notes can go with it.",
  "Open the meeting when it is ready. If it needs review, the written brief stays held until the open items are checked.",
  "Copy a skill into your assistant. Replace {meeting_id} with the meeting it should read.",
  "Export saves that same text as a file.",
];

export function Skills() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [ready, setReady] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancel = false;
    void (async () => {
      try {
        await mcp.connect();
        const listed = await mcp.listSkills();
        const loaded = await Promise.all(listed.map(async (skill) => {
          const text = await mcp.readSkill(skill.name);
          return { ...skill, text, view: "formatted" as const, copied: false };
        }));
        if (!cancel) {
          setSkills(loaded);
          setReady(true);
        }
      } catch (error) {
        if (!cancel && !(error instanceof McpDisconnected)) setMessage("Skills could not be loaded.");
        if (!cancel && error instanceof McpDisconnected) setMessage("Quotient is offline. Skills appear when it is reachable.");
      }
    })();
    return () => {
      cancel = true;
    };
  }, []);

  async function copy(skill: Skill) {
    try {
      await navigator.clipboard.writeText(skill.text);
      setSkills((current) => current.map((item) => item.name === skill.name ? { ...item, copied: true } : item));
      window.setTimeout(() => {
        setSkills((current) => current.map((item) => item.name === skill.name ? { ...item, copied: false } : item));
      }, 1600);
    } catch {
      setMessage("That skill could not be copied.");
    }
  }

  function download(skill: Skill) {
    const blob = new Blob([`# ${skill.title}\n\n${skill.text}\n`], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${skill.name}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="q-portal">
      <header className="q-page-head">
        <h1>Skills</h1>
        <p className="q-lede">Instructions a connected assistant can follow for one meeting.</p>
      </header>
      {message ? <p role="alert">{message}</p> : null}
      {!ready && !message ? <p className="q-muted">Loading skills.</p> : null}
      {ready && skills.length === 0 && !message ? <p className="q-muted">No skills are available.</p> : null}
      <div className="q-skill-list">
        {skills.map((skill) => (
          <article key={skill.name} className="q-skill">
            <div className="q-skill-head">
              <div>
                <h2>{skill.title}</h2>
                {skill.description ? <p className="q-muted">{skill.description}</p> : null}
              </div>
              <div className="q-skill-actions">
                <button
                  className="q-icon-btn"
                  type="button"
                  aria-pressed={skill.view === "formatted"}
                  aria-label="Show formatted"
                  onClick={() => setSkills((current) => current.map((item) => item.name === skill.name ? { ...item, view: "formatted" } : item))}
                >
                  <FileText size={16} aria-hidden="true" />
                </button>
                <button
                  className="q-icon-btn"
                  type="button"
                  aria-pressed={skill.view === "source"}
                  aria-label="Show source"
                  onClick={() => setSkills((current) => current.map((item) => item.name === skill.name ? { ...item, view: "source" } : item))}
                >
                  <Code size={16} aria-hidden="true" />
                </button>
                <button className="q-icon-btn" type="button" aria-label={skill.copied ? "Copied" : "Copy skill"} onClick={() => void copy(skill)}>
                  {skill.copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
                </button>
                <button className="q-icon-btn" type="button" aria-label="Export skill" onClick={() => download(skill)}>
                  <Download size={16} aria-hidden="true" />
                </button>
              </div>
            </div>
            <div className={skill.view === "source" ? "q-cell is-source" : "q-cell"} tabIndex={0}>
              {skill.view === "source" ? skill.text : <Markdown text={skill.text} />}
            </div>
          </article>
        ))}
      </div>
      <section className="q-tips-block" aria-labelledby="tips-heading">
        <h2 id="tips-heading">How to use them</h2>
        <ul className="q-tips">
          {TIPS.map((tip) => <li key={tip}>{tip}</li>)}
        </ul>
      </section>
    </main>
  );
}
