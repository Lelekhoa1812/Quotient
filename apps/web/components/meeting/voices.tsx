"use client";

/**
 * Motivation vs Logic
 * Motivation: Voices are identified automatically and a name can be wrong or missing. The person
 * reading knows who was in the room, so they must be able to fix a name where they see it, once,
 * and have every view (summary, who argued what, charts, transcript) use it from then on.
 * Logic: A name with a pencil. Saving renames the whole voice on the server, which keeps the name
 * even if the recording is analysed again. A name a person typed shows a lock; a name the machine
 * proposed does not. Long names wrap; they never squeeze the text beside them.
 */
import { Check, Lock, Pencil, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { IconButton } from "@/components/ui/moment";

export function VoiceName({
  id,
  name,
  locked,
  onRename,
  className = "",
  trigger = "pencil",
  onSelect,
}: {
  id: string;
  name: string;
  locked: boolean;
  onRename: (id: string, name: string) => Promise<void>;
  className?: string;
  /** "pencil": a visible rename button. "double-click": double-click or Enter on the name itself. */
  trigger?: "pencil" | "double-click";
  /** Called when the name is clicked (used by the transcript to focus a speaker). */
  onSelect?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const field = useRef<HTMLInputElement>(null);
  const shell = useRef<HTMLSpanElement>(null);
  const returnFocus = useRef(false);

  useEffect(() => {
    if (editing) field.current?.select();
    else if (returnFocus.current) {
      // The field is gone; without this focus falls to the page and a keyboard user loses their place.
      returnFocus.current = false;
      shell.current?.querySelector<HTMLElement>('[role="button"], button')?.focus();
    }
  }, [editing]);

  function finish() {
    returnFocus.current = true;
    setEditing(false);
  }

  function startEdit() {
    setDraft(name);
    setEditing(true);
  }

  async function save(value: string) {
    const next = value.trim();
    if (!next || next === name) {
      finish();
      return;
    }
    setBusy(true);
    setError("");
    try {
      await onRename(id, next);
      finish();
    } catch {
      setError("That did not save. Try again.");
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <span className={`q-voice-edit ${className}`}>
        <input
          ref={field}
          value={draft}
          maxLength={120}
          disabled={busy}
          aria-label={`Name for ${name}`}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            // Enter during an input-method composition only confirms the composed text; the next Enter saves.
            if (event.nativeEvent.isComposing) return;
            // Read the field itself: the state copy can lag a keystroke behind the text on screen.
            if (event.key === "Enter") {
              // A name already used by another voice opens the "Same person?" dialog during this keydown and
              // moves focus to its Cancel button; without this the same Enter press would reach Cancel and close the editor.
              event.preventDefault();
              void save(event.currentTarget.value);
            }
            if (event.key === "Escape") finish();
          }}
        />
        <IconButton label="Save name" onClick={() => void save(draft)} disabled={busy}>
          <Check size={15} aria-hidden="true" />
        </IconButton>
        <IconButton label="Cancel" onClick={finish} disabled={busy}>
          <X size={15} aria-hidden="true" />
        </IconButton>
        <span className="q-voice-hint q-faint">{error || "Kept for this meeting, even if it is analysed again."}</span>
      </span>
    );
  }

  if (trigger === "double-click") {
    return (
      <span ref={shell} className={`q-voice-name ${className}`}>
        <span
          className="q-voice-text q-voice-live"
          role="button"
          tabIndex={0}
          title="Click to focus this speaker. Double-click to rename."
          aria-label={`${name}. Double-click or press Enter to rename.`}
          onClick={() => onSelect?.()}
          onDoubleClick={startEdit}
          onKeyDown={(event) => {
            if (event.key === "Enter") startEdit();
          }}
        >
          {name}
        </span>
        {locked ? <Lock size={12} className="q-voice-lock" aria-label="Name saved by you" /> : null}
      </span>
    );
  }

  return (
    <span ref={shell} className={`q-voice-name ${className}`}>
      <span className="q-voice-text">{name}</span>
      {locked ? <Lock size={12} className="q-voice-lock" aria-label="Name saved by you" /> : null}
      <IconButton label={`Rename ${name}`} onClick={startEdit}>
        <Pencil size={14} aria-hidden="true" />
      </IconButton>
    </span>
  );
}
