"use client";

/**
 * Motivation vs Logic
 * Motivation: A mermaid fence in the brief has to become a diagram when the
 * sentence arrives, and again when the theme changes.
 * Logic: Load mermaid on the client, render with securityLevel strict, and
 * keep only an SVG whose scripts and handlers have been removed.
 */
import { useEffect, useId, useState } from "react";

type MermaidTheme = "dark" | "default";

let queue: Promise<unknown> = Promise.resolve();

function enqueue<T>(job: () => Promise<T>): Promise<T> {
  const run = queue.then(job, job);
  queue = run.then(
    () => undefined,
    () => undefined,
  );
  return run;
}

function readTheme(): MermaidTheme {
  const explicit = document.documentElement.dataset.theme;
  if (explicit === "light") return "default";
  if (explicit === "dark") return "dark";
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "default" : "dark";
}

function sanitize(svg: string): string {
  const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
  const root = doc.documentElement;
  if (root.nodeName.toLowerCase() !== "svg") return "";
  root.querySelectorAll("script, foreignObject, iframe, object, embed").forEach((node) => node.remove());
  root.querySelectorAll("*").forEach((node) => {
    for (const attr of [...node.attributes]) {
      const name = attr.name.toLowerCase();
      const value = attr.value.replace(/\s+/g, "").toLowerCase();
      if (name.startsWith("on") || value.includes("javascript:") || value.includes("data:text/html")) {
        node.removeAttribute(attr.name);
      }
    }
  });
  return new XMLSerializer().serializeToString(root);
}

export function Diagram({ source }: { source: string }) {
  const reactId = useId().replace(/:/g, "");
  const renderId = `qdiagram-${reactId}`;
  const [svg, setSvg] = useState("");
  const [failed, setFailed] = useState(false);
  const [theme, setTheme] = useState<MermaidTheme>("dark");

  useEffect(() => {
    const root = document.documentElement;
    setTheme(readTheme());
    const observer = new MutationObserver(() => setTheme(readTheme()));
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancel = false;
    setFailed(false);
    void enqueue(async () => {
      const mermaid = (await import("mermaid")).default;
      const ink = theme === "dark" ? "#ffffff" : "#001938";
      const fill = theme === "dark" ? "#102033" : "#ffffff";
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        htmlLabels: false,
        theme: "base",
        themeVariables: {
          darkMode: theme === "dark",
          background: "transparent",
          primaryColor: fill,
          primaryTextColor: ink,
          primaryBorderColor: "#125DE8",
          lineColor: "#125DE8",
          secondaryColor: fill,
          tertiaryColor: fill,
          textColor: ink,
          fontFamily: "inherit",
        },
        fontFamily: "inherit",
        suppressErrorRendering: true,
      });
      const { svg: drawn } = await mermaid.render(renderId, source);
      return sanitize(drawn);
    })
      .then((drawn) => {
        if (cancel) return;
        if (!drawn) {
          setSvg("");
          setFailed(true);
          return;
        }
        setSvg(drawn);
      })
      .catch(() => {
        if (!cancel) {
          setSvg("");
          setFailed(true);
        }
      });
    return () => {
      cancel = true;
      document.getElementById(renderId)?.remove();
    };
  }, [renderId, source, theme]);

  if (failed) {
    return <pre className="q-diagram-source">{source}</pre>;
  }
  if (!svg) return null;
  return <figure className="q-diagram" dangerouslySetInnerHTML={{ __html: svg }} />;
}
