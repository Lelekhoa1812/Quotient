"use client";

/**
 * Motivation vs Logic
 * Motivation: A business user lands to start a meeting or reopen one. The
 * first screen has to put that action first and keep protocol words off it.
 * Logic: The start band stages files and calls submit_meeting. The catalog
 * merges the local library with resources/list, then filters in the browser.
 * The backdrop is a full-screen spark field under this main, not a torus.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Pencil, Plus, Search, Trash2, Upload, X } from "lucide-react";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ContextModal } from "@/components/context-modal";
import {
  ACCEPT_ATTRIBUTE,
  EMPTY_CONTEXT,
  contextBadge,
  hasContext,
  isActive,
  isRecording,
  planAdditions,
  skippedNotice,
  splitRecordings,
  type ContextState,
} from "@/lib/context";
import { formatClock, formatWhen, meetingTitle, reviewLine, statusLabel, statusTone } from "@/lib/format";
import { hideLibrary, isHidden, readLibrary, reconcileOrphans, upsertLibrary, writeLibrary, type LibraryRecord } from "@/lib/library";
import { ContextPrepareError, McpDisconnected, mcp } from "@/lib/mcp/client";
import type { MeetingHeadline } from "@/lib/types";

const HomeObject = dynamic(() => import("@/components/home-object").then((mod) => mod.HomeObject), {
  ssr: false,
});

const HomeLoader = dynamic(() => import("@/components/home-loader").then((mod) => mod.HomeLoader), {
  ssr: false,
});

const FILTERS = [
  { id: "all", label: "All" },
  { id: "working", label: "In progress" },
  { id: "ready", label: "Ready" },
  { id: "review", label: "Needs review" },
] as const;

type FilterId = (typeof FILTERS)[number]["id"];


function primaryFile(files: File[]): File {
  return files.find((file) => isRecording(file)) ?? files[0];
}

/** True when a title is just the file's own name, so showing the file name again would repeat it. */
function sameName(title: string, filename: string): boolean {
  const key = (value: string) => value.replace(/\.[^.]+$/, "").normalize("NFKC").toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  return key(title) === key(filename);
}

function matchesFilter(status: string, filter: FilterId): boolean {
  if (filter === "all") return true;
  return statusTone(status) === filter;
}

// Same rule as sameRow in lib/library.ts: meeting id when present, otherwise task id.
function isSameRow(item: LibraryRecord, row: LibraryRecord): boolean {
  return row.meetingId ? item.meetingId === row.meetingId : item.taskId === row.taskId;
}

export function Home() {
  const router = useRouter();
  const [rows, setRows] = useState<LibraryRecord[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [over, setOver] = useState(false);
  const [message, setMessage] = useState("");
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterId>("all");
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const refocusKey = useRef<string | null>(null);
  const [draft, setDraft] = useState("");
  const [removing, setRemoving] = useState<LibraryRecord | null>(null);
  const discardEdit = useRef(false);
  // Until the first lookup pass ends, the catalog shows the waiting orbit instead of placeholder rows.
  const [enriching, setEnriching] = useState(true);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  // What each meeting was and what came out of it, from its walkaway (when it has one).
  const [headlines, setHeadlines] = useState<Record<string, MeetingHeadline>>({});
  // Reference material for the next meeting. It lives here so it survives opening and closing the modal.
  const [context, setContext] = useState<ContextState>(EMPTY_CONTEXT);
  const [contextOpen, setContextOpen] = useState(false);
  const [contextNote, setContextNote] = useState("");
  const [sending, setSending] = useState(false);
  // Set when the meeting started but some context could not be uploaded; the person opens it from here.
  const [startedTask, setStartedTask] = useState<string | null>(null);
  const contextButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let cancel = false;
    const local = readLibrary();
    setRows(local);
    void (async () => {
      try {
        await mcp.connect();
        if (cancel) return;
        const ids = await mcp.listMeetingIds();
        if (cancel) return;
        let next = readLibrary();
        for (const meetingId of ids) {
          if (isHidden(meetingId, null)) continue;
          const existing = readLibrary().find((row) => row.meetingId === meetingId);
          next = upsertLibrary({
            meetingId,
            taskId: existing?.taskId ?? null,
            title: existing?.title ?? meetingId,
            filename: existing?.filename ?? "",
            status: existing?.status ?? "",
            reviewCount: existing?.reviewCount ?? null,
            createdAt: existing?.createdAt ?? new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          });
        }
        // Bugs vs Fixes
        // Bug: Only the 20 most recent rows were looked up; the rest showed a placeholder status for
        // ever. Fix: Look up every row, newest first, six at a time, updating the list as each batch
        // lands. A row whose lookup fails is marked unknown rather than left pending.
        let rowsNow = [...next].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
        const linkOfMeeting = new Map<string, { taskId: string | null; sourceName: string | null }>();
        setRows(rowsNow.filter((row) => !isHidden(row.meetingId, row.taskId)));
        setProgress({ done: 0, total: rowsNow.length });
        for (let start = 0; start < rowsNow.length && !cancel; start += 6) {
          const batch = rowsNow.slice(start, start + 6);
          const done = await Promise.all(batch.map(async (row) => {
            if (!row.meetingId) return row;
            try {
              const status = await mcp.getMeeting(row.meetingId);
              linkOfMeeting.set(row.meetingId, { taskId: status.taskId || null, sourceName: status.sourceName || null });
              const headline = status.headline;
              if (headline && row.meetingId) setHeadlines((current) => ({ ...current, [row.meetingId as string]: headline }));
              // A meeting this browser did not create has no known creation time; use the server's.
              const known = Boolean(row.taskId);
              const when = status.updatedAt || "";
              return {
                ...row,
                status: status.status,
                reviewCount: status.reviewCount,
                title: row.title && row.title !== row.meetingId ? row.title : status.sourceName || row.title || status.meetingId,
                updatedAt: when || row.updatedAt,
                createdAt: known ? row.createdAt : when || row.createdAt,
              };
            } catch {
              return { ...row, status: "unavailable" };
            }
          }));
          rowsNow = [...rowsNow.slice(0, start), ...done, ...rowsNow.slice(start + 6)];
          // Tie a submission made on this browser to the meeting the server lists for it, so one upload is one row.
          const merged = reconcileOrphans(rowsNow, (id) => linkOfMeeting.get(id) ?? null);
          if (merged.length !== rowsNow.length) {
            rowsNow = merged.sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
            writeLibrary(rowsNow);
          }
          if (!cancel) {
            setRows(rowsNow.filter((row) => !isHidden(row.meetingId, row.taskId)));
            setProgress({ done: Math.min(start + batch.length, rowsNow.length), total: rowsNow.length });
          }
        }
      } catch (error) {
        if (!cancel && !(error instanceof McpDisconnected)) {
          setLoadError("Meetings could not be loaded.");
        }
      } finally {
        // Offline or failed, the catalog still ends its wait and shows what is stored locally.
        if (!cancel) setEnriching(false);
      }
    })();
    return () => {
      cancel = true;
    };
  }, []);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return [...rows]
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
      .filter((row) => !isHidden(row.meetingId, row.taskId))
      .filter((row) => matchesFilter(row.status, filter))
      .filter((row) => {
        if (!needle) return true;
        const headline = row.meetingId ? headlines[row.meetingId] : undefined;
        const title = row.renamed ? meetingTitle(row.title, row.filename, row.meetingId) : headline?.title || meetingTitle(row.title, row.filename, row.meetingId);
        const hay = `${title} ${row.title} ${row.filename} ${statusLabel(row.status)}`.toLowerCase();
        return hay.includes(needle);
      });
  }, [rows, query, filter, headlines]);

  /**
   * Motivation vs Logic
   * Motivation: Each catalog row needs a rename and a delete that do not
   * navigate into the meeting. The controls are symbols; the name is typed.
   * Logic: Edit writes the title through the library and keeps createdAt.
   * Delete records a hidden id so resources/list cannot put the row back.
   */
  // One title for display, editing and search: the person's own name if they chose one, else what the analysis wrote.
  useEffect(() => {
    if (editingKey !== null || refocusKey.current === null) return;
    const key = refocusKey.current;
    refocusKey.current = null;
    // The input is gone; without this focus falls to the page and a keyboard user loses their place.
    document.querySelector<HTMLElement>(`[data-edit-key="${CSS.escape(key)}"]`)?.focus();
  }, [editingKey]);

  function titleOf(row: LibraryRecord): string {
    const headline = row.meetingId ? headlines[row.meetingId] : undefined;
    return row.renamed ? meetingTitle(row.title, row.filename, row.meetingId) : headline?.title || meetingTitle(row.title, row.filename, row.meetingId);
  }

  function beginEdit(row: LibraryRecord, key: string) {
    const title = titleOf(row);
    setEditingKey(key);
    setDraft(title === "Meeting" ? "" : title);
  }

  function saveEdit(row: LibraryRecord) {
    if (discardEdit.current) {
      discardEdit.current = false;
      return;
    }
    const name = draft.trim();
    const key = editingKey;
    setEditingKey(null);
    if (!name || !key) return;
    if (name === titleOf(row)) return;
    upsertLibrary({
      ...row,
      title: name,
      renamed: true,
      createdAt: row.createdAt,
      updatedAt: row.updatedAt,
    });
    // Bug vs Fix
    // Bug: Replacing rows with the stored copy dropped each row's looked-up status, so every row showed Unknown.
    // Fix: Change only the matching row in state; the stored copy never holds the looked-up status.
    setRows((prev) => prev.map((item) => (isSameRow(item, row) ? { ...item, title: name, renamed: true } : item)));
  }

  function removeRow(row: LibraryRecord) {
    discardEdit.current = false;
    setRemoving(row);
  }

  function confirmRemove() {
    const row = removing;
    setRemoving(null);
    if (!row) return;
    setEditingKey(null);
    hideLibrary(row);
    // Same fix as saveEdit: keep the looked-up status on the rows that remain.
    setRows((prev) => prev.filter((item) => !isSameRow(item, row)));
  }

  /**
   * Motivation vs Logic
   * Motivation: Slides, notes and spreadsheets are reference, not the recording. They should land in
   * Context wherever the person drops or picks them, and a file that cannot be used should say why.
   * Logic: Recordings stay in the recording list. Everything else goes through the same rules as the
   * Context modal; accepted files join the context list and refused ones are named with their reason.
   */
  function takeFiles(picked: File[]) {
    if (busy) return; // the files are being sent; changing them now would leave some behind
    const { recordings, others } = splitRecordings(picked);
    const notes: string[] = [];
    if (recordings.length > 0) {
      // One meeting is one recording: say which one is kept instead of silently dropping the rest.
      setFiles([recordings[0]]);
      if (recordings.length > 1) notes.push(`A meeting takes one recording, so ${recordings[0].name} will be used and ${recordings.length - 1 === 1 ? "the other was" : "the others were"} left out.`);
      else if (files[0] && files[0].name !== recordings[0].name) notes.push(`${recordings[0].name} replaced ${files[0].name}.`);
    }
    if (others.length === 0) {
      if (notes.length > 0) setContextNote(notes.join(" "));
      return;
    }
    const plan = planAdditions(context.items, others);
    const kept = plan.items.filter(isActive);
    const refused = plan.items.filter((item) => !isActive(item));
    if (kept.length > 0) setContext({ ...context, items: [...context.items, ...kept] });
    const parts: string[] = [...notes];
    if (kept.length > 0) parts.push(`Added ${kept.length} ${kept.length === 1 ? "file" : "files"} to Context.`);
    for (const item of refused) parts.push(`${item.name} was not added: ${item.reason}.`);
    if (plan.notice) parts.push(plan.notice);
    setContextNote(parts.join(" "));
  }

  async function onSubmit() {
    const primary = files[0] ? primaryFile(files) : null;
    // The name is optional: a recording is usually named well enough by its file.
    const title = name.trim() || (primary ? primary.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim() : "");
    if (!primary || !title) return;
    setBusy(true);
    setMessage("");
    setContextNote("");
    setStartedTask(null);
    const failed = new Set<string>();
    const sendingContext = hasContext(context);
    if (sendingContext) {
      setSending(true);
      setContext((current) => ({ ...current, items: current.items.map((item) => ({ ...item, status: "ready", progress: 0, reason: "" })) }));
    }
    try {
      const task = await mcp.submitMeeting(
        primary,
        files.filter((file) => file !== primary),
        title,
        sendingContext
          ? {
              items: context.items,
              purpose: context.purpose,
              onItem: (id, update) => {
                if (update.status === "failed") failed.add(id);
                setContext((current) => ({ ...current, items: current.items.map((item) => (item.id === id ? { ...item, ...update } : item)) }));
              },
            }
          : undefined,
      );
      const skipped = context.items.filter((item) => failed.has(item.id)).map((item) => item.name);
      if (skipped.length === 0) {
        router.push(`/tasks/${task.taskId}`);
        return;
      }
      // The meeting is under way. Say what it left out and let the person open it when they have read that.
      setContextNote(skippedNotice(skipped));
      setStartedTask(task.taskId);
      setSending(false);
      // The meeting has started: clear the form so the same recording cannot be started twice by mistake.
      setFiles([]);
      setName("");
      setContext(EMPTY_CONTEXT);
      setBusy(false);
    } catch (error) {
      setSending(false);
      if (error instanceof ContextPrepareError) {
        setContext((current) => ({ ...current, items: current.items.map((item) => ({ ...item, status: "ready", progress: 0, reason: "" })) }));
        setMessage(`The meeting was not started. The context could not be prepared: ${error.message.replace(/\.$/, "")}. Try again, or remove the context to start without it.`);
      } else {
        setMessage(
          error instanceof McpDisconnected
            ? "Quotient is offline, so the recording was not sent. Start Quotient and try again."
            : sendingContext
              ? "The meeting could not be started. Try again, or remove the context to start without it."
              : "The meeting could not be started. Check that the file is an audio or video recording and try again.",
        );
      }
      setBusy(false);
    }
  }

  const emptyCopy = rows.length === 0
    ? "Meetings you start appear here."
    : query.trim()
      ? "Nothing matches that search."
      : "Nothing matches that filter.";

  return (
    <main id="main" tabIndex={-1} className="q-portal">
      {/* Motivation vs Logic
          Motivation: Sparks should cover the screen and stay out of the way of the start band.
          Logic: Render the field first, fixed to the viewport, so the sheets paint above it. */}
      <HomeObject />
      <section
        className={over ? "q-start is-over" : "q-start"}
        aria-labelledby="start-heading"
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setOver(false);
          takeFiles([...event.dataTransfer.files]);
        }}
      >
        <div className="q-start-copy">
          <h1 id="start-heading">Start a meeting</h1>
          <p className="q-lede">Name the meeting and add a recording. Slides, notes and other reference go in Context.</p>
          <label className="q-start-name">
            <span>Meeting name</span>
            <input
              value={name}
              placeholder="Optional. Defaults to the file name"
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <div className="q-start-actions">
            <label className="q-btn-ghost">
              <Upload size={16} aria-hidden="true" />
              Add files
              <input
                className="q-sr"
                type="file"
                multiple
                accept={`video/*,audio/*,${ACCEPT_ATTRIBUTE}`}
                onChange={(event) => {
                  takeFiles([...(event.target.files ?? [])]);
                  event.target.value = "";
                }}
              />
            </label>
            <button
              ref={contextButton}
              className="q-btn-ghost"
              type="button"
              disabled={busy}
              aria-haspopup="dialog"
              title="Give the analysis reference material about this meeting"
              onClick={() => setContextOpen(true)}
            >
              <Plus size={16} aria-hidden="true" />
              {contextBadge(context)}
            </button>
            <button
              className="q-btn"
              type="button"
              disabled={files.length === 0 || busy}
              onClick={() => void onSubmit()}
            >
              {busy ? "Starting" : "Start analysis"}
            </button>
          </div>
          {files.length > 0 ? (
            <ul className="q-files">
              {files.map((file) => (
                <li key={`${file.name}:${file.size}:${file.lastModified}`}>
                  <span>{file.name}</span>
                  <button
                    className="q-icon-btn"
                    type="button"
                    aria-label={`Remove ${file.name}`}
                    onClick={() => setFiles((current) => current.filter((item) => item !== file))}
                  >
                    <X size={14} aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {sending && context.items.length > 0 ? (
            <p className="q-ctx-sending q-faint" role="status">
              Sending context · {context.items.filter((item) => (item.status === "ready" && item.progress === 1) || item.status === "failed").length} of {context.items.length}
            </p>
          ) : null}
          {contextNote ? <p className="q-ctx-home-note" role="status">{contextNote}</p> : null}
          {startedTask ? (
            <p>
              <Link className="q-btn" href={`/tasks/${startedTask}`}>Open the meeting</Link>
            </p>
          ) : null}
          {message ? <p role="alert">{message}</p> : null}
        </div>
      </section>


      <section className="q-catalog" aria-labelledby="meetings-heading">
        <div className="q-catalog-head">
          <h2 id="meetings-heading">Meetings</h2>
          <label className="q-search">
            <span className="q-sr">Search meetings</span>
            <Search size={16} aria-hidden="true" />
            <input
              value={query}
              placeholder="Name or file"
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
        </div>
        {enriching && rows.length === 0 ? <HomeLoader done={progress.done} total={progress.total} /> : (
          <>
            {rows.length > 0 ? (
              <div className="q-filters" role="group" aria-label="Filter meetings">
                {FILTERS.map((item) => (
                  <button
                    key={item.id}
                    className="q-filter"
                    type="button"
                    aria-pressed={filter === item.id}
                    onClick={() => setFilter(item.id)}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            ) : null}
            {loadError ? <p role="alert">{loadError}</p> : null}
            {shown.length === 0 ? <p className="q-muted">{emptyCopy}</p> : null}
            <div className="q-meeting-list">
              {shown.map((row) => {
                const href = row.meetingId ? `/meetings/${row.meetingId}` : row.taskId ? `/tasks/${row.taskId}` : "/";
                const key = row.meetingId ?? row.taskId ?? row.updatedAt;
                const headline = row.meetingId ? headlines[row.meetingId] : undefined;
                const title = titleOf(row);
                const created = row.createdAt || row.updatedAt;
                const stamp = [formatWhen(created), formatClock(created)].filter(Boolean).join(" ");
                const review = reviewLine(row.reviewCount);
                const outcome = headline ? outcomeLine(headline) : "";
                const meta = [stamp, outcome || review].filter(Boolean).join(" · ");
                const label = statusLabel(row.status) || (row.taskId ? "Working" : "");
                const editing = editingKey === key;
                return (
                  <div key={key} className="q-meeting">
                    {editing ? (
                      <div className="q-meeting-main">
                        <input
                          className="q-meeting-name"
                          value={draft}
                          aria-label={`Name for ${title}`}
                          autoFocus
                          onFocus={(event) => event.target.select()}
                          onChange={(event) => setDraft(event.target.value)}
                          onBlur={() => saveEdit(row)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              event.preventDefault();
                              refocusKey.current = key;
                              saveEdit(row);
                            }
                            if (event.key === "Escape") {
                              discardEdit.current = true;
                              refocusKey.current = key;
                              setEditingKey(null);
                            }
                          }}
                        />
                        {meta ? <span className="q-meeting-meta">{meta}</span> : null}
                      </div>
                    ) : (
                      <Link className="q-meeting-main" href={href}>
                        <span className="q-meeting-title">{title}</span>
                        {row.filename && !sameName(title, row.filename) ? <span className="q-meeting-file">{row.filename}</span> : null}
                        {headline?.summary ? <span className="q-meeting-gist">{headline.summary}</span> : null}
                        {meta ? <span className="q-meeting-meta">{meta}</span> : null}
                      </Link>
                    )}
                    <span className="q-meeting-actions">
                      <button
                        className="q-icon-btn"
                        type="button"
                        aria-label={`Edit name for ${title}`}
                        data-edit-key={key}
                        onMouseDown={(event) => {
                          if (editing) event.preventDefault();
                        }}
                        onClick={() => {
                          if (editing) saveEdit(row);
                          else beginEdit(row, key);
                        }}
                      >
                        <Pencil size={14} aria-hidden="true" />
                      </button>
                      <button
                        className="q-icon-btn"
                        type="button"
                        aria-label={`Remove ${title} from the list`}
                        onMouseDown={() => {
                          discardEdit.current = true;
                        }}
                        onClick={() => removeRow(row)}
                      >
                        <Trash2 size={14} aria-hidden="true" />
                      </button>
                    </span>
                    {label ? <span className="q-status" data-tone={statusTone(row.status)}>{label}</span> : <span className="q-status" data-tone="quiet">{enriching ? "…" : "Unknown"}</span>}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </section>
      <ContextModal
        open={contextOpen}
        saved={context}
        returnFocus={contextButton}
        onSave={(next) => {
          setContext(next);
          setContextNote("");
        }}
        onClose={() => setContextOpen(false)}
      />
      <ConfirmDialog
        open={removing !== null}
        title="Remove this meeting from this computer's list?"
        message="The recording and its analysis are not deleted; the meeting is only hidden from this list."
        confirmLabel="Remove"
        cancelLabel="Cancel"
        onConfirm={confirmRemove}
        onCancel={() => setRemoving(null)}
      />
    </main>
  );
}

const KIND_LABEL: Record<string, string> = {
  meeting: "Meeting",
  presentation: "Presentation",
  lecture: "Lecture",
  discussion: "Discussion",
  interview: "Interview",
};

function outcomeLine(headline: MeetingHeadline): string {
  const parts = [KIND_LABEL[headline.contentType] ?? ""];
  if (headline.decisions) parts.push(`${headline.decisions} ${headline.decisions === 1 ? "decision" : "decisions"}`);
  if (headline.actions) parts.push(`${headline.actions} ${headline.actions === 1 ? "action" : "actions"}`);
  if (headline.openQuestions) parts.push(`${headline.openQuestions} open ${headline.openQuestions === 1 ? "question" : "questions"}`);
  return parts.filter(Boolean).join(" · ");
}
