"use client";

/**
 * Motivation vs Logic
 * Motivation: Business users need a stable way home and a plain notice when
 * Quotient cannot be reached. A healthy connection should stay quiet.
 * Logic: The header probes the session once. Only a failed probe renders a
 * banner. The page body stays mounted either way.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, Moon, Sun } from "lucide-react";
import { mcp, type Phase } from "@/lib/mcp/client";
import { useSyncExternalStore } from "react";

function subscribe(listener: () => void): () => void {
  return mcp.subscribe(listener);
}

export function useMcpPhase(): Phase {
  return useSyncExternalStore(subscribe, () => mcp.phase(), () => "idle");
}

/**
 * Motivation vs Logic
 * Motivation: Meetings, MCP, and Settings must stay one tap away without crowding the logo, and the same three links have to fit a narrow viewport.
 * Logic: One link list feeds the inline bar and the dropdown. Below 768px a Menu button toggles the panel, which closes on a link, Escape, or a resize back to desktop.
 */
const PRIMARY_LINKS = [
  { href: "/", label: "Meetings" },
  { href: "/mcp", label: "MCP" },
  { href: "/settings", label: "Settings" },
] as const;

function isCurrent(pathname: string, href: (typeof PRIMARY_LINKS)[number]["href"]): boolean {
  if (href === "/") {
    return pathname === "/" || pathname.startsWith("/meetings") || pathname.startsWith("/tasks");
  }
  if (href === "/mcp") return pathname === "/mcp" || pathname.startsWith("/mcp/");
  return pathname === "/settings" || pathname.startsWith("/settings/");
}

function PrimaryLinks({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return (
    <>
      {PRIMARY_LINKS.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          aria-current={isCurrent(pathname, item.href) ? "page" : undefined}
          onClick={onNavigate}
        >
          {item.label}
        </Link>
      ))}
    </>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">("dark");

  useEffect(() => {
    const stored = document.documentElement.dataset.theme;
    if (stored === "light" || stored === "dark") {
      setTheme(stored);
      return;
    }
    setTheme(window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  }, []);

  function apply(next: "light" | "dark") {
    document.documentElement.dataset.theme = next;
    localStorage.setItem("quotient-theme", next);
    setTheme(next);
  }

  const next = theme === "light" ? "dark" : "light";
  return (
    <button
      className="q-theme"
      type="button"
      aria-label={theme === "light" ? "Use dark theme" : "Use light theme"}
      onClick={() => apply(next)}
    >
      {theme === "light" ? <Moon size={16} aria-hidden="true" /> : <Sun size={16} aria-hidden="true" />}
    </button>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const phase = useMcpPhase();
  const pathname = usePathname();
  const connecting = phase === "idle" || phase === "connecting";
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (mcp.phase() === "idle") {
      void mcp.connect().catch(() => undefined);
    }
  }, [phase]);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 768px)");
    function closeOnDesktop() {
      if (desktop.matches) setMenuOpen(false);
    }
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  return (
    <div className="q-app">
      <header className="q-header">
        {/*
          Motivation vs Logic
          Motivation: The header brand is Axion's mark on both themes. mark.jpg is matted on white, so dark mode needs the same X with that plate removed.
          Logic: Two sources, one visible. CSS follows the theme tokens: mark.jpg on light, mark-dark.png on dark.
        */}
        <Link href="/" className="q-brand">
          <img className="is-light" src="/mark.jpg" alt="Axion" width={32} height={32} />
          <img className="is-dark" src="/mark-dark.png" alt="Axion" width={32} height={32} />
          <span className="q-wordmark">QUOTIENT</span>
        </Link>
        <nav className="q-topnav" aria-label="Primary">
          <PrimaryLinks pathname={pathname} />
        </nav>
        <div className="q-header-end">
          {connecting ? <span className="q-quiet">Connecting</span> : null}
          <button
            className="q-nav-toggle"
            type="button"
            aria-label="Menu"
            aria-expanded={menuOpen}
            aria-controls="q-nav-panel"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <Menu size={16} aria-hidden="true" />
          </button>
          <ThemeToggle />
        </div>
        <div className={menuOpen ? "q-nav-panel is-open" : "q-nav-panel"} id="q-nav-panel">
          <nav aria-label="Primary">
            <PrimaryLinks pathname={pathname} onNavigate={() => setMenuOpen(false)} />
          </nav>
        </div>
      </header>
      {phase === "disconnected" ? (
        <div className="q-banner" role="status">
          <p>Quotient is offline. Meetings saved on this computer are still listed.</p>
          <button
            className="q-btn-ghost"
            type="button"
            onClick={() => {
              mcp.reset();
              void mcp.connect().catch(() => undefined);
            }}
          >
            Try again
          </button>
        </div>
      ) : null}
      <div className="q-body">{children}</div>
    </div>
  );
}
