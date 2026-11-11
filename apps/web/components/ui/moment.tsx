"use client";

/**
 * Motivation vs Logic
 * Motivation: Every claim, decision and figure has a moment in the recording. A full-width
 * "Hear the moment" button per item made lists unreadable; a time and a speaker icon say the same.
 * Logic: One compact control: speaker icon plus m:ss. The accessible name says what it does.
 * IconButton is the shared icon-only button with a tooltip and an aria-label.
 */
import { wordForTranscript } from "@/lib/present";
import { createContext, useContext, type ReactNode } from "react";
import { Volume2 } from "lucide-react";
import { formatMs } from "@/lib/format";

/**
 * Whether the page has a recording to play. A transcript meeting has none, so every moment on it is
 * shown as a time, not as a control that would seek.
 */
export const PlayableContext = createContext(true);

export function usePlayable(): boolean {
  return useContext(PlayableContext);
}

/**
 * Words that name the source. A transcript meeting has no recording and no video, so the sentences that say
 * "the recording" say "the transcript" there, and the one about the video says where the names came from.
 */
export function useWording(): (text: string) => string {
  const playable = usePlayable();
  return playable ? (text) => text : wordForTranscript;
}

/** The same as useWording for text written straight into the page. */
export function Wording({ children }: { children: string }) {
  return <>{useWording()(children)}</>;
}

export function Moment({ ms, onPlay, label }: { ms: number | null; onPlay: (ms: number) => void; label?: string }) {
  const playable = usePlayable();
  if (ms === null) return null;
  const time = formatMs(ms);
  if (!playable) {
    return (
      <span className="q-moment is-static" title={`${time} in the transcript`}>
        <span>{time}</span>
      </span>
    );
  }
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
  const w = useWording();
  if (basis !== "likely") return null;
  return (
    <span className="q-likely" title={w("Likely: the words are in the recording; one check was not certain.")}>
      <span aria-hidden="true">◐</span>
      <span className="q-sr">Likely</span>
    </span>
  );
}
