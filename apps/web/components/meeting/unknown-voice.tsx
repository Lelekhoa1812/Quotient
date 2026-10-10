"use client";

/**
 * Motivation vs Logic
 * Motivation: When the analysis cannot tell who a voice is, the transcript keeps "Speaker 3". The person
 * reading can usually say who it is if they can hear it: a few clear stretches from across the recording.
 * Logic: A red person-with-rotating-arrows button marks each such voice in "Who spoke". It opens a
 * dialog with the voice's best three stretches as short playable clips (the recording itself, cut by a
 * media fragment, so nothing is downloaded or rendered), and two ways out: type a name, or choose a
 * person who was already detected, which merges this voice into theirs. The dialog only collects the
 * decision; the page saves it, so a name that clashes with an existing one still asks the merge question.
 * Clips unmount when the dialog closes, so nothing keeps playing behind it.
 */
import { useEffect, useId, useRef, useState } from "react";
import { Check, Merge } from "lucide-react";
import { formatMs } from "@/lib/format";
import { mcp } from "@/lib/mcp/client";
import type { Candidate, Slice } from "@/lib/voices";

/** A person with a circular arrow around them: "work out who this is". Drawn here because no icon in the set combines the two. */
export function IdentifyIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <circle cx="12" cy="9.6" r="2.5" />
      <path d="M7.9 16.6c.7-2 2.3-3.1 4.1-3.1s3.4 1.1 4.1 3.1" />
      <path d="M20 12a8 8 0 0 0-13.7-5.6L4.5 8.2" />
      <path d="M4.5 3.8v4.4h4.4" />
      <path d="M4 12a8 8 0 0 0 13.7 5.6l1.8-1.8" />
      <path d="M19.5 20.2v-4.4h-4.4" />
    </svg>
  );
}

/** The red marker beside a voice nobody has named. */
export function UnknownVoiceButton({ label, onOpen }: { label: string; onOpen: () => void }) {
  return (
    <button type="button" className="q-unknown-btn" data-tip="Identify this speaker" aria-label={`Identify ${label}`} onClick={onOpen}>
      <IdentifyIcon size={16} />
    </button>
  );
}

function useMediaSource(source: string): { url: string; note: string } {
  const [state, setState] = useState({ url: "", note: "" });
  useEffect(() => {
    let cancel = false;
    void (async () => {
      if (!source) {
        setState({ url: "", note: "The recording isn't available for playback." });
        return;
      }
      try {
        const url = source.startsWith("quotient://") ? (await mcp.readResource(source)).href ?? "" : source;
        if (!cancel) setState({ url, note: url ? "" : "The recording isn't available for playback." });
      } catch {
        if (!cancel) setState({ url: "", note: "The recording could not be loaded." });
      }
    })();
    return () => {
      cancel = true;
    };
  }, [source]);
  return state;
}

export function UnknownVoiceDialog({
  open,
  label,
  slices,
  candidates,
  source,
  busy = false,
  onName,
  onRegister,
  onClose,
}: {
  open: boolean;
  /** How the voice reads now, for example "Speaker 3". */
  label: string;
  slices: Slice[];
  candidates: Candidate[];
  /** The recording's playback URI (quotient:// or a URL). */
  source: string;
  busy?: boolean;
  onName: (name: string) => void;
  onRegister: (candidate: Candidate) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const hintId = useId();
  const inputId = useId();
  const [name, setName] = useState("");
  const media = useMediaSource(open ? source : "");

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setName("");
      dialog.showModal();
    } else if (!open && dialog.open) dialog.close();
  }, [open]);

  const trimmed = name.trim();
  return (
    <dialog
      ref={ref}
      className="q-dialog q-voice-dialog"
      aria-labelledby={titleId}
      aria-describedby={hintId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      {open ? (
        <div className="q-dialog-body">
          <h2 id={titleId}>Who is {label}?</h2>
          <p id={hintId} className="q-muted">
            Listen to where this voice spoke, then name them, or pick someone already detected if it is the same person.
          </p>
          {media.note ? <p className="q-muted" role="status">{media.note}</p> : null}
          {slices.length === 0 ? <p className="q-muted">No clear stretch of this voice was found.</p> : null}
          <ol className="q-clips">
            {slices.map((slice, index) => (
              <li key={`${slice.id}-${slice.startMs}`} className="q-clip">
                <video
                  className="q-clip-video"
                  src={media.url ? `${media.url}#t=${(slice.startMs / 1000).toFixed(2)},${(slice.endMs / 1000).toFixed(2)}` : undefined}
                  controls
                  preload="metadata"
                  playsInline
                  aria-label={`Clip ${index + 1} of ${label}, from ${formatMs(slice.startMs)}`}
                />
                <p className="q-clip-text">
                  <span className="q-num">{formatMs(slice.startMs)}</span> {slice.text.length > 200 ? `${slice.text.slice(0, 200).trimEnd()}…` : slice.text}
                </p>
              </li>
            ))}
          </ol>
          <form
            className="q-voice-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (trimmed && !busy) onName(trimmed);
            }}
          >
            <label htmlFor={inputId}>Their name</label>
            <div className="q-voice-form-row">
              <input id={inputId} value={name} maxLength={120} autoComplete="off" onChange={(event) => setName(event.target.value)} />
              <button type="submit" className="q-btn" disabled={!trimmed || busy}>
                <Check size={15} aria-hidden="true" /> Save name
              </button>
            </div>
          </form>
          {candidates.length > 0 ? (
            <div className="q-voice-register">
              <p className="q-faint" id={`${hintId}-who`}>Or this is someone already detected:</p>
              <ul className="q-chips" aria-labelledby={`${hintId}-who`}>
                {candidates.map((candidate) => (
                  <li key={candidate.id}>
                    <button type="button" className="q-chip-btn" disabled={busy} onClick={() => onRegister(candidate)}>
                      <Merge size={14} aria-hidden="true" /> {candidate.name}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="q-dialog-actions">
            <button type="button" className="q-btn q-btn-ghost" onClick={onClose}>Not now</button>
          </div>
        </div>
      ) : null}
    </dialog>
  );
}
