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
import { Check, Pencil, Search, Trash2, Upload, X } from "lucide-react";
import { formatClock, formatWhen, meetingTitle, reviewLine, statusLabel, statusTone } from "@/lib/format";
import { hideLibrary, isHidden, readLibrary, upsertLibrary, type LibraryRecord } from "@/lib/library";
import { McpDisconnected, mcp } from "@/lib/mcp/client";

const HomeObject = dynamic(() => import("@/components/home-object").then((mod) => mod.HomeObject), {
  ssr: false,
});

const FILTERS = [
  { id: "all", label: "All" },
  { id: "working", label: "In progress" },
  { id: "ready", label: "Ready" },
  { id: "review", label: "Needs review" },
] as const;

type FilterId = (typeof FILTERS)[number]["id"];

const ASSURANCES = [
  "Recording or call audio",
  "Slides, decks, and notes",
  "A written brief when it is ready",
];

function primaryFile(files: File[]): File {
  return files.find((file) => file.type.startsWith("video/") || file.type.startsWith("audio/")) ?? files[0];
}

function matchesFilter(status: string, filter: FilterId): boolean {
  if (filter === "all") return true;
  return statusTone(status) === filter;
}

export function Home() {
  const router = useRouter();
  const [rows, setRows] = useState<LibraryRecord[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [over, setOver] = useState(false);
  const [message, setMessage] = useState("");
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterId>("all");
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const discardEdit = useRef(false);

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
        const enriched = await Promise.all(next.slice(0, 20).map(async (row) => {
          if (!row.meetingId) return row;
          try {
            const status = await mcp.getMeeting(row.meetingId);
            return { ...row, status: status.status, reviewCount: status.reviewCount, title: row.title || status.meetingId };
          } catch {
            return row;
          }
        }));
        if (!cancel) setRows(enriched.filter((row) => !isHidden(row.meetingId, row.taskId)));
      } catch (error) {
        if (!cancel && !(error instanceof McpDisconnected)) {
          setLoadError("Meetings could not be loaded.");
        }
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
        const title = meetingTitle(row.title, row.filename, row.meetingId);
        const hay = `${title} ${row.filename} ${statusLabel(row.status)}`.toLowerCase();
        return hay.includes(needle);
      });
  }, [rows, query, filter]);

  /**
   * Motivation vs Logic
   * Motivation: Each catalog row needs a rename and a delete that do not
   * navigate into the meeting. The controls are symbols; the name is typed.
   * Logic: Edit writes the title through the library and keeps createdAt.
   * Delete records a hidden id so resources/list cannot put the row back.
   */
  function beginEdit(row: LibraryRecord, key: string) {
    const title = meetingTitle(row.title, row.filename, row.meetingId);
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
    const current = meetingTitle(row.title, row.filename, row.meetingId);
    if (name === current) return;
    const next = upsertLibrary({
      ...row,
      title: name,
      createdAt: row.createdAt,
      updatedAt: row.updatedAt,
    });
    setRows(next);
  }

  function removeRow(row: LibraryRecord) {
    discardEdit.current = false;
    setEditingKey(null);
    setRows(hideLibrary(row));
  }

  async function onSubmit() {
    const primary = files[0] ? primaryFile(files) : null;
    if (!primary) return;
    setBusy(true);
    setMessage("");
    try {
      const task = await mcp.submitMeeting(primary, files.filter((file) => file !== primary));
      router.push(`/tasks/${task.taskId}`);
    } catch (error) {
      if (!(error instanceof McpDisconnected)) setMessage("The meeting could not be started.");
      setBusy(false);
    }
  }

  const emptyCopy = rows.length === 0
    ? "Meetings you start appear here."
    : query.trim()
      ? "Nothing matches that search."
      : "Nothing matches that filter.";

  return (
    <main className="q-portal">
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
          setFiles([...event.dataTransfer.files]);
        }}
      >
        <div className="q-start-copy">
          <h1 id="start-heading">Start a meeting</h1>
          <p className="q-lede">Add a recording. Slides and notes are optional.</p>
          <div className="q-start-actions">
            <label className="q-btn-ghost">
              <Upload size={16} aria-hidden="true" />
              Add files
              <input
                className="q-sr"
                type="file"
                multiple
                accept="video/*,audio/*,.pdf,.docx,.pptx,.xlsx,.csv,.png,.jpg,.jpeg,.webp"
                onChange={(event) => setFiles([...(event.target.files ?? [])])}
              />
            </label>
            <button className="q-btn" type="button" disabled={files.length === 0 || busy} onClick={() => void onSubmit()}>
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
          {message ? <p role="alert">{message}</p> : null}
        </div>
      </section>

      <ul className="q-assurances">
        {ASSURANCES.map((item) => (
          <li key={item}>
            <Check size={16} aria-hidden="true" />
            <span>{item}</span>
          </li>
        ))}
      </ul>

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
            const title = meetingTitle(row.title, row.filename, row.meetingId);
            const created = row.createdAt || row.updatedAt;
            const stamp = [formatWhen(created), formatClock(created)].filter(Boolean).join(" ");
            const review = reviewLine(row.reviewCount);
            const meta = [stamp, review].filter(Boolean).join(" · ");
            const label = statusLabel(row.status) || (row.taskId ? "Working" : "Queued");
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
                      onChange={(event) => setDraft(event.target.value)}
                      onBlur={() => saveEdit(row)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          saveEdit(row);
                        }
                        if (event.key === "Escape") {
                          discardEdit.current = true;
                          setEditingKey(null);
                        }
                      }}
                    />
                    {meta ? <span className="q-meeting-meta">{meta}</span> : null}
                  </div>
                ) : (
                  <Link className="q-meeting-main" href={href}>
                    <span className="q-meeting-title">{title}</span>
                    {meta ? <span className="q-meeting-meta">{meta}</span> : null}
                  </Link>
                )}
                <span className="q-meeting-actions">
                  <button
                    className="q-icon-btn"
                    type="button"
                    aria-label={`Edit name for ${title}`}
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
                    aria-label={`Delete ${title}`}
                    onMouseDown={() => {
                      discardEdit.current = true;
                    }}
                    onClick={() => removeRow(row)}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </span>
                <span className="q-status" data-tone={statusTone(row.status)}>{label}</span>
              </div>
            );
          })}
        </div>
      </section>
    </main>
  );
}
