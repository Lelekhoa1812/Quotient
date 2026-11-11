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
import { useMcpPhase } from "@/components/shell";
import {
  ACCEPT_ATTRIBUTE,
  EMPTY_CONTEXT,
  classifyFile,
  contextBadge,
  hasContext,
  isActive,
  isRecording,
  planAdditions,
  skippedNotice,
  type ContextItem,
  type ContextState,
} from "@/lib/context";
import { formatClock, formatWhen, meetingTitle, reviewLine, statusLabel, statusTone } from "@/lib/format";
import { hideLibrary, isHidden, readLibrary, reconcileOrphans, upsertLibrary, writeLibrary, type LibraryRecord } from "@/lib/library";
import { ContextPrepareError, McpDisconnected, mcp } from "@/lib/mcp/client";
import {
  TRANSCRIPT_ACCEPT,
  choosePrimary,
  isSubtitleFile,
  isTranscriptFile,
} from "@/lib/mcp/upload";
import { loadPreference, submitModelArgs, type ModelOptions, type SubmitModelArgs } from "@/lib/models";
import { friendlyError } from "@/lib/present";
import type { MeetingHeadline, ModelProvider } from "@/lib/types";

const HomeObject = dynamic(() => import("@/components/home-object").then((mod) => mod.HomeObject), {
  ssr: false,
});

const HomeLoader = dynamic(() => import("@/components/home-loader").then((mod) => mod.HomeLoader), {
  ssr: false,
});

const QuantumLoader = dynamic(
  () => import("@/components/quantum-loader").then((mod) => mod.QuantumLoader),
  { ssr: false }
);

const FILTERS = [
  { id: "all", label: "All" },
  { id: "working", label: "In progress" },
  { id: "ready", label: "Ready" },
  { id: "review", label: "Needs review" },
] as const;

type FilterId = (typeof FILTERS)[number]["id"];


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
  // Which model family analysed each meeting, so a NIM meeting can say so in the list.
  const [providers, setProviders] = useState<Record<string, ModelProvider>>({});
  // Reference material for the next meeting. It lives here so it survives opening and closing the modal.
  const [context, setContext] = useState<ContextState>(EMPTY_CONTEXT);
  const [contextOpen, setContextOpen] = useState(false);
  const [contextNote, setContextNote] = useState("");
  const [sending, setSending] = useState(false);
  const [bypassed, setBypassed] = useState(false);
  // Set when the meeting started but some context could not be uploaded; the person opens it from here.
  const [startedMeeting, setStartedMeeting] = useState<string | null>(null);
  const [uploadPercent, setUploadPercent] = useState<number | null>(null);
  const contextButton = useRef<HTMLButtonElement>(null);
  const phase = useMcpPhase();
  const connecting = phase === "idle" || phase === "connecting";

  useEffect(() => {
    let cancel = false;
    const local = readLibrary();
    setRows(local);
    setEnriching(true);
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
        for (let start = 0; start < rowsNow.length && !cancel; start += 2) {
          const batch = rowsNow.slice(start, start + 2);
          const done = await Promise.all(batch.map(async (row) => {
            if (!row.meetingId) return row;
            try {
              let status: Awaited<ReturnType<typeof mcp.getMeeting>>;
              try {
                status = await mcp.getMeeting(row.meetingId);
              } catch {
                await new Promise((res) => setTimeout(res, 600));
                status = await mcp.getMeeting(row.meetingId);
              }
              linkOfMeeting.set(row.meetingId, { taskId: status.taskId || null, sourceName: status.sourceName || null });
              const provider = status.modelProvider;
              if (provider && row.meetingId) setProviders((current) => ({ ...current, [row.meetingId as string]: provider }));
              const headline = status.headline;
              if (headline && row.meetingId) setHeadlines((current) => ({ ...current, [row.meetingId as string]: headline }));
              // A meeting this browser did not create has no known creation time; use the server's.
              const known = Boolean(row.taskId);
              const when = status.updatedAt || "";
              const serverTitle = headline?.title || status.sourceName || status.meetingId;
              return {
                ...row,
                status: status.status,
                reviewCount: status.reviewCount,
                title: row.renamed ? row.title : (serverTitle || row.title),
                updatedAt: when || row.updatedAt,
                createdAt: known ? row.createdAt : when || row.createdAt,
              };
            } catch {
              return { ...row, status: row.status && row.status !== "unavailable" ? row.status : "unavailable" };
            }
          }));
          rowsNow = [...rowsNow.slice(0, start), ...done, ...rowsNow.slice(start + 2)];
          // Tie a submission made on this browser to the meeting the server lists for it, so one upload is one row.
          const merged = reconcileOrphans(rowsNow, (id) => linkOfMeeting.get(id) ?? null);
          rowsNow = merged.sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
          writeLibrary(rowsNow);
          if (!cancel) {
            setRows(rowsNow.filter((row) => !isHidden(row.meetingId, row.taskId)));
            setProgress({ done: Math.min(start + batch.length, rowsNow.length), total: rowsNow.length });
            await new Promise((res) => setTimeout(res, 50));
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
  }, [phase]);

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
    if (row.meetingId) {
      void mcp.renameMeeting(row.meetingId, name).catch(() => undefined);
    }
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
   * Motivation: Slides, notes and spreadsheets are reference, not the recording. A transcript (SRT or VTT,
   * or a text document when no recording is picked) is the meeting's own words, so it becomes the primary
   * input instead. Whatever the person drops, a file that cannot be used should say why.
   * Logic: One primary input at a time (a recording or a transcript), chosen by choosePrimary. Other
   * documents go through the same rules as the Context modal; refused ones are named with their reason.
   * A subtitle file is always the transcript, and any extra recording or transcript is left out with a note.
   */
  function takeFiles(picked: File[]) {
    if (busy) return; // the files are being sent; changing them now would leave some behind
    const current = files[0] ?? null;
    const choice = choosePrimary(current, picked);
    const next = choice.primary;
    const parts: string[] = [];
    const toContext: File[] = [];
    if (next !== current) setFiles(next ? [next] : []);
    if (next && current && next !== current) parts.push(`${next.name} replaced ${current.name}.`);
    if (next && !current && !isRecording(next)) parts.push(`${next.name} is the transcript.`);
    if (choice.displaced && !isRecording(choice.displaced)) {
      toContext.push(choice.displaced);
      parts.push(`${choice.displaced.name} went back to Context.`);
    }
    const left = choice.rest.filter((file) => isRecording(file) || isSubtitleFile(file.name));
    if (left.length > 0) {
      parts.push(`A meeting takes one recording or transcript, so ${left.map((file) => file.name).join(", ")} ${left.length === 1 ? "was" : "were"} left out.`);
    }
    toContext.push(...choice.rest.filter((file) => !isRecording(file) && !isSubtitleFile(file.name)));
    if (toContext.length > 0) {
      const plan = planAdditions(context.items, toContext);
      const kept = plan.items.filter(isActive);
      const refused = plan.items.filter((item) => !isActive(item));
      if (kept.length > 0) {
        setContext({ ...context, items: [...context.items, ...kept] });
        parts.push(`Added ${kept.length} ${kept.length === 1 ? "file" : "files"} to Context.`);
      }
      for (const item of refused) parts.push(`${item.name} was not added: ${item.reason}.`);
      if (plan.notice) parts.push(plan.notice);
    }
    if (parts.length > 0) setContextNote(parts.join(" "));
  }

  /** Use a Context document as the transcript. Not offered while a recording is the primary input. */
  function useAsTranscript(item: ContextItem) {
    if (busy || !item.file) return;
    const current = files[0] ?? null;
    if (current && isRecording(current)) return;
    const file = item.file;
    const remaining = context.items.filter((entry) => entry.id !== item.id);
    const back = current ? planAdditions(remaining, [current]).items.filter(isActive) : [];
    setContext({ ...context, items: [...remaining, ...back] });
    setFiles([file]);
    const parts = [`${file.name} is the transcript.`];
    if (current) parts.push(`${current.name} went back to Context.`);
    setContextNote(parts.join(" "));
  }

  /** Keep the transcript as Context instead. Offered only for files that can be Context. */
  function useAsContext(file: File) {
    if (busy || !classifyFile(file).ok) return;
    setFiles([]);
    const kept = planAdditions(context.items, [file]).items.filter(isActive);
    if (kept.length > 0) setContext({ ...context, items: [...context.items, ...kept] });
    setContextNote(`${file.name} is now Context. Add a recording or a transcript to start.`);
  }

  async function onSubmit() {
    const primary = files[0] ?? null;
    // The name is optional: a recording or transcript is usually named well enough by its file.
    const title = name.trim() || (primary ? primary.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim() : "");
    if (!primary || !title) return;
    setBusy(true);
    setMessage("");
    setContextNote("");
    setStartedMeeting(null);
    setUploadPercent(null);
    const failed = new Set<string>();
    const sendingContext = hasContext(context);
    if (sendingContext) {
      setSending(true);
      setContext((current) => ({ ...current, items: current.items.map((item) => ({ ...item, status: "ready", progress: 0, reason: "" })) }));
    }
    try {
      const models = await chosenModels();
      const started = await mcp.submitMeeting(
        primary,
        [],
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
        models,
        (fraction) => setUploadPercent(Math.round(fraction * 100)),
      );
      setUploadPercent(null);
      const skipped = context.items.filter((item) => failed.has(item.id)).map((item) => item.name);
      if (skipped.length === 0) {
        router.push(`/meetings/${started.meetingId}`);
        return;
      }
      // The meeting is under way. Say what it left out and let the person open it when they have read that.
      setContextNote(skippedNotice(skipped));
      setStartedMeeting(started.meetingId);
      setSending(false);
      // The meeting has started: clear the form so the same recording cannot be started twice by mistake.
      setFiles([]);
      setName("");
      setContext(EMPTY_CONTEXT);
      setBusy(false);
    } catch (error) {
      setSending(false);
      setUploadPercent(null);
      if (error instanceof ContextPrepareError) {
        setContext((current) => ({ ...current, items: current.items.map((item) => ({ ...item, status: "ready", progress: 0, reason: "" })) }));
        setMessage(`The meeting was not started. The context could not be prepared: ${error.message.replace(/\.$/, "")}. Try again, or remove the context to start without it.`);
      } else {
        const generic = sendingContext
          ? "The meeting could not be started. Try again, or remove the context to start without it."
          : "The meeting could not be started. Check that the file is a recording or a transcript and try again.";
        setMessage(
          error instanceof McpDisconnected
            ? "Quotient cloud service is unreachable. Please wait a moment for services to wake up and try again."
            : error instanceof Error
              ? friendlyError(error.message, generic)
              : generic,
        );
      }
      setBusy(false);
    }
  }

  /**
   * The model family chosen in Settings, read when the meeting starts. A failed lookup of the server's
   * choices does not stop the meeting: the saved choice is sent as it is, or nothing when none is saved.
   */
  async function chosenModels(): Promise<SubmitModelArgs | null> {
    let options: ModelOptions | null = null;
    try {
      options = await mcp.modelOptions();
    } catch (error) {
      if (error instanceof McpDisconnected) throw error;
    }
    return submitModelArgs(loadPreference(), options);
  }

  // A transcript can be picked from Context only while no recording is the primary input.
  const recordingPicked = files.some((file) => isRecording(file));
  const contextTranscripts = recordingPicked
    ? []
    : context.items.filter((item) => item.file !== null && isActive(item) && isTranscriptFile(item.name));

  const emptyCopy = rows.length === 0
    ? connecting
      ? "Starting Quotient and looking for meetings…"
      : "Meetings you start appear here."
    : query.trim()
      ? "Nothing matches that search."
      : "Nothing matches that filter.";

  return (
    <main id="main" tabIndex={-1} className="q-portal">
      {(connecting || enriching) && !bypassed ? (
        <QuantumLoader
          phase={phase}
          enriching={enriching}
          progress={progress}
          onBypass={() => setBypassed(true)}
          hasCachedData={rows.length > 0}
        />
      ) : null}
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
          <p className="q-lede">Name the meeting and add a recording or a transcript (SRT, VTT, TXT, MD, DOCX, PDF).</p>
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
                accept={`video/*,audio/*,${ACCEPT_ATTRIBUTE},${TRANSCRIPT_ACCEPT}`}
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
              {files.map((file) => {
                const transcript = !isRecording(file);
                // A subtitle file is always the transcript; only a readable document can go back to Context.
                const canBeContext = transcript && !isSubtitleFile(file.name) && classifyFile(file).ok;
                return (
                  <li key={`${file.name}:${file.size}:${file.lastModified}`}>
                    <span>{file.name}</span>
                    <span className="q-faint">{transcript ? "Transcript" : "Recording"}</span>
                    {canBeContext ? (
                      <button className="q-link" type="button" disabled={busy} onClick={() => useAsContext(file)}>
                        Use as context
                      </button>
                    ) : null}
                    <button
                      className="q-icon-btn"
                      type="button"
                      aria-label={`Remove ${file.name}`}
                      onClick={() => setFiles((current) => current.filter((item) => item !== file))}
                    >
                      <X size={14} aria-hidden="true" />
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : null}
          {contextTranscripts.length > 0 ? (
            <ul className="q-files" aria-label="Context files that can be the transcript">
              {contextTranscripts.map((item) => (
                <li key={item.id}>
                  <span>{item.name}</span>
                  <span className="q-faint">Context</span>
                  <button className="q-link" type="button" disabled={busy} onClick={() => useAsTranscript(item)}>
                    Use as transcript
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
          {uploadPercent !== null ? <p className="q-faint" role="status">Uploading {files[0]?.name ?? "the file"} · {uploadPercent}%</p> : null}
          {contextNote ? <p className="q-ctx-home-note" role="status">{contextNote}</p> : null}
          {startedMeeting ? (
            <p>
              <Link className="q-btn" href={`/meetings/${startedMeeting}`}>Open the meeting</Link>
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
        {enriching && rows.length === 0 ? (
          <HomeLoader
            done={progress.done}
            total={progress.total}
            title={connecting ? "Starting Quotient" : "Loading your meetings"}
            subtitle={connecting ? "Warming up cloud services on AWS…" : undefined}
          />
        ) : (
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
                        {row.meetingId && providers[row.meetingId] === "nim" ? <span className="q-badge" title="Analysed with NVIDIA NIM">NIM</span> : null}
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
                    {label ? (
                      <span className="q-status" data-tone={statusTone(row.status)}>{label}</span>
                    ) : (
                      <span className="q-status" data-tone={connecting || enriching ? "working" : "quiet"}>
                        {connecting || enriching ? (
                          <>
                            <span className="q-pulse-dot" aria-hidden="true" style={{ marginRight: 6 }} />
                            Syncing…
                          </>
                        ) : (
                          "Cached"
                        )}
                      </span>
                    )}
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
        title="Remove this meeting from your browser's saved list?"
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
