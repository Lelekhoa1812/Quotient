"use client";

/**
 * Motivation vs Logic
 * Motivation: Two voices can be given the same name, either by a typo or because two people really
 * share a name. Only the reader knows which, so the portal asks before it merges anything.
 * Logic: A native dialog like the confirm box. Merge joins the two voices everywhere. Differ keeps
 * them apart and marks the renamed voice "(ex)" so the extra person is visible. Cancel changes nothing.
 */
import { useEffect, useId, useRef } from "react";

export function SameVoiceDialog({
  open,
  name,
  onMerge,
  onDiffer,
  onCancel,
}: {
  open: boolean;
  name: string;
  onMerge: () => void;
  onDiffer: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const messageId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="q-dialog"
      aria-labelledby={titleId}
      aria-describedby={messageId}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div className="q-dialog-body">
        <h2 id={titleId}>Same person?</h2>
        <p id={messageId} className="q-muted">
          Another speaker is already called <strong>{name}</strong>. Are they the same person?
        </p>
        <ul className="q-same-voice-options">
          <li>
            <strong>Merge</strong>: treat them as one speaker everywhere.
          </li>
          <li>
            <strong>Differ</strong>: keep them apart. This speaker is named <strong>{name} (ex)</strong> to flag an extra person.
          </li>
        </ul>
        <div className="q-dialog-actions">
          <button className="q-btn-ghost" type="button" onClick={onCancel}>
            Cancel
          </button>
          <button className="q-btn-ghost" type="button" onClick={onDiffer}>
            Differ
          </button>
          <button className="q-btn" type="button" onClick={onMerge}>
            Merge
          </button>
        </div>
      </div>
    </dialog>
  );
}
