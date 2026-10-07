/**
 * Motivation vs Logic
 * Motivation: The library has to list meetings this browser started even when
 * the MCP server is down, and merge server resource URIs when it is up.
 * Logic: Persist id, task, filename, status, and the first-seen createdAt in
 * localStorage. Resource URIs contribute meeting ids. Hidden ids stay out of
 * the union so a deleted row does not return on the next resources/list.
 */

export type LibraryRecord = {
  meetingId: string | null;
  taskId: string | null;
  title: string;
  filename: string;
  status: string;
  reviewCount: number | null;
  createdAt: string;
  updatedAt: string;
};

const KEY = "quotient.library";
const HIDDEN_KEY = "quotient.library.hidden";

function storage(): Storage | null {
  if (typeof window === "undefined") return null;
  return window.localStorage;
}

export function readLibrary(): LibraryRecord[] {
  const store = storage();
  if (!store) return [];
  const raw = store.getItem(KEY);
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((item) => {
      if (typeof item !== "object" || item === null) return [];
      const record = item as Partial<LibraryRecord>;
      if (typeof record.title !== "string" || typeof record.updatedAt !== "string") return [];
      return [{
        meetingId: record.meetingId ?? null,
        taskId: record.taskId ?? null,
        title: record.title,
        filename: record.filename ?? "",
        status: record.status ?? "",
        reviewCount: record.reviewCount ?? null,
        createdAt: typeof record.createdAt === "string" ? record.createdAt : record.updatedAt,
        updatedAt: record.updatedAt,
      }];
    });
  } catch {
    return [];
  }
}

export function writeLibrary(records: LibraryRecord[]): void {
  storage()?.setItem(KEY, JSON.stringify(records.slice(0, 100)));
}

export function upsertLibrary(record: LibraryRecord): LibraryRecord[] {
  const current = readLibrary();
  const prior = current.find((item) => sameRow(item, record));
  const stored: LibraryRecord = {
    ...record,
    createdAt: prior?.createdAt ?? record.createdAt ?? record.updatedAt,
  };
  const next = [stored, ...current.filter((item) => !sameRow(item, record))];
  writeLibrary(next);
  return next;
}

/**
 * Motivation vs Logic
 * Motivation: Delete has to take a meeting off this browser's catalog. The
 * server still lists the resource, so a storage-only removal comes back.
 * Logic: Record the meeting id and task id, drop the row, and let the catalog
 * skip those ids when it merges resources/list.
 */
export function hideLibrary(record: Pick<LibraryRecord, "meetingId" | "taskId">): LibraryRecord[] {
  const hidden = readHidden();
  if (record.meetingId) hidden.add(record.meetingId);
  if (record.taskId) hidden.add(`task:${record.taskId}`);
  storage()?.setItem(HIDDEN_KEY, JSON.stringify([...hidden]));
  const next = readLibrary().filter((item) => !sameRow(item, record as LibraryRecord));
  writeLibrary(next);
  return next;
}

export function isHidden(meetingId: string | null, taskId: string | null): boolean {
  const hidden = readHidden();
  if (meetingId && hidden.has(meetingId)) return true;
  if (taskId && hidden.has(`task:${taskId}`)) return true;
  return false;
}

function readHidden(): Set<string> {
  const raw = storage()?.getItem(HIDDEN_KEY);
  if (!raw) return new Set();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((item): item is string => typeof item === "string" && item.length > 0));
  } catch {
    return new Set();
  }
}

function sameRow(left: LibraryRecord, right: LibraryRecord): boolean {
  if (left.meetingId && right.meetingId) return left.meetingId === right.meetingId;
  if (left.taskId && right.taskId) return left.taskId === right.taskId;
  return false;
}

export function meetingIdFromUri(uri: string): string | null {
  const prefix = "quotient://meetings/";
  if (!uri.startsWith(prefix)) return null;
  const rest = uri.slice(prefix.length);
  const slash = rest.indexOf("/");
  const id = slash === -1 ? rest : rest.slice(0, slash);
  return id.length > 0 ? id : null;
}
