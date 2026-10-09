"use client";

/**
 * Motivation vs Logic
 * Motivation: Every claim, decision and figure has a moment in the recording. A full-width
 * "Hear the moment" button per item made lists unreadable; a time and a speaker icon say the same.
 * Logic: One compact control: speaker icon plus m:ss. The accessible name says what it does.
 * IconButton is the shared icon-only button with a tooltip and an aria-label.
 */
import type { ReactNode } from "react";
import { Volume2 } from "lucide-react";
import { formatMs } from "@/lib/format";

export function Moment({ ms, onPlay, label }: { ms: number | null; onPlay: (ms: number) => void; label?: string }) {
  if (ms === null) return null;
  const time = formatMs(ms);
  return (
    <button
      type="button"
      className="q-moment"
      onClick={() => onPlay(ms)}
      title={`Play from ${time}`}
      aria-label={label ? `Play “${label}” from ${time}` : `Play from ${time}`}
    >
      <Volume2 size={14} aria-hidden="true" />
      <span>{time}</span>
    </button>
  );
}

export function IconButton({
  label,
  onClick,
  children,
  pressed,
  disabled,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
  pressed?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className={pressed ? "q-icon-btn is-on" : "q-icon-btn"}
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={pressed}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

/** A small marker for items resting on "likely" evidence; confirmed items carry no marker. */
export function Likely({ basis }: { basis: string }) {
  if (basis !== "likely") return null;
  return (
    <span className="q-likely" title="Likely: the words are in the recording; one check was not certain.">
      <span aria-hidden="true">◐</span>
      <span className="q-sr">Likely</span>
    </span>
  );
}
