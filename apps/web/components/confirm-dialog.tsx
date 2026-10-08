"use client";

/**
 * Motivation vs Logic
 * Motivation: A confirmation has to match the portal's look. The browser's own
 * confirm box ignores the theme and the type, so it reads as a different app.
 * Logic: A native dialog opened with showModal, so focus stays inside, Escape
 * and a backdrop click cancel, and the page behind is inert. Cancel comes first
 * in the DOM, so it takes focus on open and Enter keeps the item.
 */
import { useEffect, useId, useRef } from "react";

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  cancelLabel = "Cancel",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
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
        // Escape would close the dialog on its own; route it through onCancel so the parent state stays in step.
        event.preventDefault();
        onCancel();
      }}
      onClick={(event) => {
        // Only the dialog box itself is the backdrop; clicks inside it land on .q-dialog-body.
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div className="q-dialog-body">
        <h2 id={titleId}>{title}</h2>
        <p id={messageId} className="q-muted">{message}</p>
        <div className="q-dialog-actions">
          <button className="q-btn-ghost" type="button" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button className="q-btn" type="button" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  );
}
