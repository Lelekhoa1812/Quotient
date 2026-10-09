"use client";

/**
 * Motivation vs Logic
 * Motivation: The analysis does better when it knows what the meeting is for, what the product is
 * called and who is involved. The person has that material (slides, a brief, a glossary) and needs a
 * calm place to hand it over, in the open and on a phone, without it feeling like a form dump. What
 * they add is reference for the analysis, never something said in the meeting, and the modal says so.
 * Logic: A native dialog opened with showModal, mounted only while open so every opening starts from
 * the saved context. Edits go to a draft; Save commits it, Cancel drops it. Escape and a backdrop
 * click ask once before losing unsaved changes. Rejected files stay in the list with their reason.
 * Focus wraps inside, the page behind does not scroll, and focus returns to the "+ Context" button.
 * All rules (types, limits, naming) live in lib/context.ts.
 */
import {
  ClipboardPaste,
  Code,
  FileText,
  FolderOpen,
  Lock,
  Paperclip,
  Plus,
  Presentation,
  StickyNote,
  Table,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import {
  ACCEPTED_TYPES,
  ACCEPT_ATTRIBUTE,
  MAX_NOTE_CHARS,
  MAX_PURPOSE_CHARS,
  REASON_NAME,
  REASON_SIZE,
  cleanForSave,
  defaultNoteTitle,
  extensionOf,
  formatBytes,
  planAdditions,
  planNote,
  sameContext,
  totalsLine,
  withNoteText,
  type ContextItem,
  type ContextKind,
  type ContextState,
} from "@/lib/context";

const ICONS: Record<ContextKind, typeof FileText> = {
  document: FileText,
  table: Table,
  slides: Presentation,
  code: Code,
  note: StickyNote,
};

type Tab = "files" | "paste";

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), summary, [href], [tabindex]:not([tabindex="-1"])';

function count(value: number): string {
  return value.toLocaleString("en-AU");
}

export function ContextModal({
  open,
  saved,
  onSave,
  onClose,
  returnFocus,
}: {
  open: boolean;
  saved: ContextState;
  onSave: (next: ContextState) => void;
  onClose: () => void;
  returnFocus: RefObject<HTMLElement | null>;
}) {
  if (!open) return null;
  return <ContextDialog saved={saved} onSave={onSave} onClose={onClose} returnFocus={returnFocus} />;
}

function ContextDialog({
  saved,
  onSave,
  onClose,
  returnFocus,
}: {
  saved: ContextState;
  onSave: (next: ContextState) => void;
  onClose: () => void;
  returnFocus: RefObject<HTMLElement | null>;
}) {
  const ids = useId();
  const titleId = `${ids}-title`;
  const aboutId = `${ids}-about`;
  const dialog = useRef<HTMLDialogElement>(null);
  const purposeField = useRef<HTMLTextAreaElement>(null);
  const noteTitleField = useRef<HTMLInputElement>(null);
  const keepButton = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const tabButtons = useRef<Record<Tab, HTMLButtonElement | null>>({ files: null, paste: null });
  const pressedOnBackdrop = useRef(false);
  const focusAfterRemove = useRef<number | null>(null);
  const afterCancel = useRef(false);

  const [draft, setDraft] = useState<ContextState>(() => ({ purpose: saved.purpose, items: [...saved.items] }));
  const [tab, setTab] = useState<Tab>("files");
  const [noteTitle, setNoteTitle] = useState("");
  const [noteText, setNoteText] = useState("");
  const [notice, setNotice] = useState("");
  const [over, setOver] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const dirty = !sameContext(draft, saved);
  const summary = totalsLine(draft.items);

  // Open as a modal, lock the page behind it, and hand focus back to the button on the way out.
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (!element.open) element.showModal();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // On a phone, focusing the field would raise the keyboard over the sheet before it is read.
    if (window.matchMedia("(min-width: 641px)").matches) purposeField.current?.focus();
    const target = returnFocus.current;
    return () => {
      // The dialog element leaves the page with this component, which also ends its modal state.
      document.body.style.overflow = previous;
      target?.focus();
    };
  }, [returnFocus]);

  useEffect(() => {
    if (confirming) keepButton.current?.focus();
  }, [confirming]);

  // After a row is removed its button is gone; move focus to its neighbour instead of losing it.
  useEffect(() => {
    const index = focusAfterRemove.current;
    if (index === null) return;
    focusAfterRemove.current = null;
    const buttons = list.current?.querySelectorAll<HTMLButtonElement>("[data-ctx-remove]");
    const next = buttons && buttons.length > 0 ? buttons[Math.min(index, buttons.length - 1)] : tabButtons.current[tab];
    next?.focus();
  }, [draft.items, tab]);

  // Bugs vs Fixes
  // Bug: Chrome closes a modal dialog on a second Escape pressed with no click or key in between,
  // even when the first was cancelled. The dialog closed but this component still counted as open,
  // so "+ Context" could not open it again and unsaved changes were lost without asking.
  // Fix: When the dialog closes by itself while this component is mounted, put it back. With unsaved
  // changes, Escape toggles the discard prompt; without, it closes for real.
  function onNativeClose() {
    // For one key press Chrome can fire cancel (handled in onCancel) and then close, some 150ms later.
    const handled = afterCancel.current;
    afterCancel.current = false;
    const element = dialog.current;
    if (!element?.isConnected) return;
    if (!dirty && !handled) {
      onClose();
      return;
    }
    element.showModal();
    if (!handled) setConfirming((current) => !current);
  }

  function requestClose() {
    // While the discard prompt is up, only its own Discard button closes; the X and the backdrop leave it standing.
    if (dirty) setConfirming(true);
    else onClose();
  }

  function save() {
    onSave(cleanForSave(draft));
    onClose();
  }

  function addFiles(files: File[]) {
    if (files.length === 0) return;
    const plan = planAdditions(draft.items, files);
    setDraft({ ...draft, items: [...draft.items, ...plan.items] });
    setNotice(plan.notice);
  }

  function addNote() {
    const result = planNote(draft.items, noteTitle, noteText);
    setNotice(result.notice);
    if (!result.item) return;
    setDraft({ ...draft, items: [...draft.items, result.item] });
    setNoteTitle("");
    setNoteText("");
    // The Add button disables itself once the form is empty, which would drop focus to the page.
    // The title field is where the next note starts.
    noteTitleField.current?.focus();
  }

  function remove(index: number) {
    focusAfterRemove.current = index;
    setDraft({ ...draft, items: draft.items.filter((_, position) => position !== index) });
    setNotice("");
  }

  function editNote(id: string, text: string) {
    setDraft({ ...draft, items: draft.items.map((item) => (item.id === id ? withNoteText(item, text) : item)) });
  }

  function onKeyDown(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key !== "Tab" || !dialog.current) return;
    // Only what can be reached now: nothing in a hidden tab panel or a closed <details>.
    const reachable = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((node) => node.closest("[hidden]") === null && node.getClientRects().length > 0);
    if (reachable.length === 0) return;
    const first = reachable[0];
    const last = reachable[reachable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function onTabKey(event: KeyboardEvent<HTMLButtonElement>, current: Tab) {
    const order: Tab[] = ["files", "paste"];
    const at = order.indexOf(current);
    let next: Tab | null = null;
    if (event.key === "ArrowRight") next = order[(at + 1) % order.length];
    else if (event.key === "ArrowLeft") next = order[(at - 1 + order.length) % order.length];
    else if (event.key === "Home") next = order[0];
    else if (event.key === "End") next = order[order.length - 1];
    if (!next) return;
    event.preventDefault();
    setTab(next);
    tabButtons.current[next]?.focus();
  }

  return (
    <dialog
      ref={dialog}
      className="q-ctx"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={aboutId}
      onKeyDown={onKeyDown}
      onClose={onNativeClose}
      onCancel={(event) => {
        // Escape would close the dialog by itself; route it through the same guard as the backdrop.
        event.preventDefault();
        // A cancel that cannot be cancelled is followed by a close event; onNativeClose then puts the dialog back.
        afterCancel.current = !event.cancelable;
        if (confirming) setConfirming(false);
        else requestClose();
      }}
      onMouseDown={(event) => {
        pressedOnBackdrop.current = event.target === event.currentTarget;
      }}
      onClick={(event) => {
        // Only a press that started and ended on the backdrop closes; a text selection dragged out does not.
        if (event.target === event.currentTarget && pressedOnBackdrop.current) requestClose();
      }}
      onDragEnter={(event) => {
        if (event.dataTransfer.types.includes("Files")) setOver(true);
      }}
      onDragOver={(event) => {
        event.preventDefault();
        if (event.dataTransfer.types.includes("Files")) setOver(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(false);
      }}
      onDrop={(event) => {
        // A drop anywhere on the sheet adds the files; without this the browser would open the file instead.
        event.preventDefault();
        setOver(false);
        if (event.dataTransfer.files.length > 0) {
          setTab("files");
          addFiles([...event.dataTransfer.files]);
        }
      }}
    >
      <header className="q-ctx-head">
        <div className="q-ctx-head-text">
          <h2 id={titleId}>Context for this meeting</h2>
          <p id={aboutId} className="q-muted">
            Tell the analysis what this meeting is about and give it the documents it should know, such as the product, the problem, a glossary or who is involved.
          </p>
          <p className="q-ctx-privacy">
            <Lock size={13} aria-hidden="true" />
            <span>Sent with the recording to the analysis service. Used as reference, never as what was said.</span>
          </p>
        </div>
        <button className="q-icon-btn" type="button" aria-label="Close" title="Close" onClick={requestClose}>
          <X size={16} aria-hidden="true" />
        </button>
      </header>

      <div className="q-ctx-body">
        <section className="q-ctx-section" aria-labelledby={`${ids}-purpose`}>
          <h3 id={`${ids}-purpose`}><label htmlFor={`${ids}-purpose-field`}>What is this meeting about?</label></h3>
          <textarea
            id={`${ids}-purpose-field`}
            ref={purposeField}
            className="q-ctx-field"
            rows={4}
            maxLength={MAX_PURPOSE_CHARS}
            value={draft.purpose}
            placeholder="Optional. For example: the weekly review of the billing app, where we decide whether to ship the new invoice export before the audit."
            aria-describedby={`${ids}-purpose-count`}
            onChange={(event) => setDraft({ ...draft, purpose: event.target.value })}
          />
          <p id={`${ids}-purpose-count`} className="q-ctx-count q-faint">
            {count(draft.purpose.length)} / {count(MAX_PURPOSE_CHARS)}
          </p>
        </section>

        <section className="q-ctx-section" aria-label="Reference material">
          <div className="q-ctx-tabs" role="tablist" aria-label="How to add reference material">
            <button
              ref={(node) => {
                tabButtons.current.files = node;
              }}
              id={`${ids}-tab-files`}
              className="q-ctx-tab"
              type="button"
              role="tab"
              aria-selected={tab === "files"}
              aria-controls={`${ids}-panel-files`}
              tabIndex={tab === "files" ? 0 : -1}
              onClick={() => setTab("files")}
              onKeyDown={(event) => onTabKey(event, "files")}
            >
              <Paperclip size={15} aria-hidden="true" />
              Files
            </button>
            <button
              ref={(node) => {
                tabButtons.current.paste = node;
              }}
              id={`${ids}-tab-paste`}
              className="q-ctx-tab"
              type="button"
              role="tab"
              aria-selected={tab === "paste"}
              aria-controls={`${ids}-panel-paste`}
              tabIndex={tab === "paste" ? 0 : -1}
              onClick={() => setTab("paste")}
              onKeyDown={(event) => onTabKey(event, "paste")}
            >
              <ClipboardPaste size={15} aria-hidden="true" />
              Paste text
            </button>
          </div>

          <div id={`${ids}-panel-files`} role="tabpanel" aria-labelledby={`${ids}-tab-files`} hidden={tab !== "files"} className="q-ctx-panel">
            <div className={over ? "q-ctx-drop is-over" : "q-ctx-drop"}>
              <Upload size={22} aria-hidden="true" />
              <p className="q-ctx-drop-title">Drop files here</p>
              <label className="q-btn-ghost q-ctx-browse">
                <FolderOpen size={16} aria-hidden="true" />
                Browse files
                <input
                  className="q-sr"
                  type="file"
                  multiple
                  accept={ACCEPT_ATTRIBUTE}
                  onChange={(event) => {
                    addFiles([...(event.target.files ?? [])]);
                    event.target.value = "";
                  }}
                />
              </label>
              <p className="q-ctx-formats">
                PDF, Word, PowerPoint, Excel, CSV, JSON, XML, HTML, Markdown, text and EPUB. Up to 25 MB each, 20 items and 100 MB in total.
              </p>
            </div>
          </div>

          <div id={`${ids}-panel-paste`} role="tabpanel" aria-labelledby={`${ids}-tab-paste`} hidden={tab !== "paste"} className="q-ctx-panel">
            <label className="q-ctx-label">
              <span>Title (optional)</span>
              <input
                ref={noteTitleField}
                className="q-ctx-field"
                value={noteTitle}
                maxLength={80}
                placeholder={defaultNoteTitle(draft.items)}
                onChange={(event) => setNoteTitle(event.target.value)}
              />
            </label>
            <label className="q-ctx-label">
              <span>Text</span>
              <textarea
                className="q-ctx-field"
                rows={7}
                maxLength={MAX_NOTE_CHARS}
                value={noteText}
                placeholder="Paste a brief, a glossary, an email thread, or anything else the analysis should know."
                aria-describedby={`${ids}-note-count`}
                onChange={(event) => setNoteText(event.target.value)}
              />
            </label>
            <div className="q-ctx-note-bar">
              <span id={`${ids}-note-count`} className="q-ctx-count q-faint">
                {count(noteText.length)} / {count(MAX_NOTE_CHARS)}
              </span>
              <button className="q-btn-ghost" type="button" disabled={noteText.trim().length === 0} onClick={addNote}>
                <Plus size={16} aria-hidden="true" />
                Add note
              </button>
            </div>
          </div>
        </section>

        <p className="q-ctx-notice" role="status" aria-live="polite">{notice}</p>

        <section className="q-ctx-section" aria-labelledby={`${ids}-added`}>
          <div className="q-ctx-list-head">
            <h3 id={`${ids}-added`}>Added</h3>
            <span className="q-ctx-total q-faint" aria-live="polite">{summary}</span>
          </div>
          {draft.items.length === 0 ? (
            <p className="q-faint">Nothing added yet. Files and notes stay on this page until you start the analysis.</p>
          ) : (
            <ul ref={list} className="q-ctx-list">
              {draft.items.map((item, index) => (
                <ItemRow key={item.id} item={item} onRemove={() => remove(index)} onEdit={(text) => editNote(item.id, text)} />
              ))}
            </ul>
          )}
        </section>
      </div>

      <footer className="q-ctx-foot">
        {confirming ? (
          <div className="q-ctx-confirm" role="alert">
            <p>Discard your changes to this context?</p>
            <div className="q-ctx-actions">
              <button ref={keepButton} className="q-btn-ghost" type="button" onClick={() => setConfirming(false)}>
                Keep editing
              </button>
              <button className="q-btn" type="button" onClick={onClose}>
                Discard
              </button>
            </div>
          </div>
        ) : (
          <>
            {draft.items.length > 0 ? (
              <button className="q-ctx-clear" type="button" onClick={() => setDraft({ ...draft, items: [] })}>
                <Trash2 size={14} aria-hidden="true" />
                Clear all
              </button>
            ) : <span />}
            <div className="q-ctx-actions">
              <button className="q-btn-ghost" type="button" onClick={onClose}>
                Cancel
              </button>
              <button className="q-btn" type="button" onClick={save}>
                Save context
              </button>
            </div>
          </>
        )}
      </footer>
    </dialog>
  );
}

function chipFor(item: ContextItem): { text: string; tone: "ready" | "busy" | "bad" } {
  if (item.status === "uploading") return { text: `Uploading ${Math.round(item.progress * 100)}%`, tone: "busy" };
  if (item.status === "failed") return { text: "Couldn't upload", tone: "bad" };
  if (item.status === "rejected") return { text: item.reason === REASON_SIZE ? "Too large" : item.reason === REASON_NAME ? "Name too long" : "Not supported", tone: "bad" };
  return { text: "Ready", tone: "ready" };
}

function ItemRow({ item, onRemove, onEdit }: { item: ContextItem; onRemove: () => void; onEdit: (text: string) => void }) {
  const Icon = ICONS[item.kind];
  const chip = chipFor(item);
  const label = item.kind === "note" ? "Pasted note" : ACCEPTED_TYPES[extensionOf(item.name)]?.label ?? "";
  const measure = item.kind === "note" ? `${count(item.chars ?? 0)} characters` : formatBytes(item.size);
  const meta = [label, measure].filter(Boolean).join(" · ");
  return (
    <li className="q-ctx-item" data-status={item.status}>
      <span className="q-ctx-icon" aria-hidden="true"><Icon size={18} /></span>
      <div className="q-ctx-main">
        <span className="q-ctx-name">{item.name}</span>
        <span className="q-ctx-meta q-faint">{meta}</span>
        {item.reason ? <span className="q-ctx-reason">{item.reason}</span> : null}
      </div>
      <span className="q-ctx-chip" data-tone={chip.tone}>{chip.text}</span>
      <button
        className="q-icon-btn"
        type="button"
        data-ctx-remove=""
        aria-label={`Remove ${item.name}`}
        title={`Remove ${item.name}`}
        onClick={onRemove}
      >
        <X size={14} aria-hidden="true" />
      </button>
      {item.status === "uploading" ? <span className="q-ctx-bar" aria-hidden="true" style={{ width: `${Math.round(item.progress * 100)}%` }} /> : null}
      {item.kind === "note" && item.text !== null ? (
        <details className="q-ctx-edit">
          <summary>Read or edit</summary>
          <textarea
            className="q-ctx-field"
            rows={6}
            maxLength={MAX_NOTE_CHARS}
            value={item.text}
            aria-label={`Text of ${item.name}`}
            onChange={(event) => onEdit(event.target.value)}
          />
          <p className="q-ctx-count q-faint">{count(item.text.length)} / {count(MAX_NOTE_CHARS)}</p>
        </details>
      ) : null}
    </li>
  );
}
