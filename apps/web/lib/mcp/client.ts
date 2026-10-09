/**
 * Motivation vs Logic
 * Motivation: The portal is an MCP client of POST /mcp on the same origin.
 * Meeting screens have to render when that server is down.
 * Logic: Negotiate protocol 2025-11-25, keep the session header, and call the
 * Quotient tools. submit_meeting is task-augmented. tasks/get is polled.
 * input_required opens tasks/result and answers elicitation. Transport
 * failures set an explicit disconnected phase without throwing away the UI.
 */

import { emptyGraph, mergeGraph, parseGraph, parseMeetingId, parseMeetingStatus, unwrapTool } from "@/lib/graph";
import { asArray, asFinite, asRecord, asString } from "@/lib/json";
import { meetingIdFromUri, readLibrary, upsertLibrary } from "@/lib/library";
import {
  UPLOAD_CONCURRENCY,
  buildPrepareArgs,
  parsePrepareResult,
  runPool,
  toUploads,
  type ContextItem,
} from "@/lib/context";
import { mediaTypeOf, prepareElicitationContent, putFile } from "@/lib/mcp/upload";
import type { GraphPage, MeetingStatus, TaskSnapshot } from "@/lib/types";

export type SkillSummary = {
  name: string;
  title: string;
  description: string;
};

export type ToolCatalog = {
  name: string;
  title: string;
  description: string;
  inputSchema: Record<string, unknown> | null;
};

export class McpDisconnected extends Error {
  constructor(message = "Quotient MCP is disconnected") {
    super(message);
    this.name = "McpDisconnected";
  }
}

/** The service answered prepare_context with a plain error. The meeting is not started. */
export class ContextPrepareError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ContextPrepareError";
  }
}

/** Reference material for one submission, plus an optional hook that reports each item's upload. */
export type SubmitContext = {
  items: ContextItem[];
  purpose: string;
  onItem?: (id: string, update: Partial<Pick<ContextItem, "status" | "progress" | "reason">>) => void;
};

export type Phase = "idle" | "connecting" | "connected" | "disconnected";

type JsonRpc = {
  id?: number | string;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: { message?: string };
};

type CoreTask = {
  taskId: string;
  status: string;
  statusMessage: string;
  pollInterval: number;
  meetingId: string | null;
};

/**
 * Read-only link the portal already sends. apiUrl is the partner-contract
 * local default and the rewrite target when QUOTIENT_MCP_URL is unset.
 * The browser calls same-origin endpointPath.
 */
const parameters = {
  endpointPath: "/mcp",
  protocolVersion: "2025-11-25",
  protocolHeader: "MCP-Protocol-Version",
  sessionHeader: "MCP-Session-Id",
  apiUrl: "http://127.0.0.1:8080/mcp",
} as const;

const listeners = new Set<() => void>();
const tasks = new Map<string, TaskSnapshot>();
const staged = new Map<string, File[]>();
const fileWaiters = new Map<string, (files: File[]) => void>();
const resultPromises = new Map<string, Promise<unknown>>();
const resultWaiters = new Set<string>();
const watches = new Set<string>();
const tokenToTask = new Map<string, string>();

let phase: Phase = "idle";
let detail = "POST /mcp has not been contacted yet";
let sessionId: string | null = null;
let initialized = false;
let nextId = 0;
let connectPromise: Promise<void> | null = null;
let channel: AbortController | null = null;
let activeTaskId: string | null = null;
let toolNames = new Set<string>();

function emit(): void {
  for (const listener of listeners) listener();
}

function setPhase(next: Phase, message?: string): void {
  phase = next;
  if (message) detail = message;
  emit();
}

function snapshotFrom(core: CoreTask, previous: TaskSnapshot | undefined): TaskSnapshot {
  return {
    taskId: core.taskId,
    status: core.status,
    statusMessage: core.statusMessage,
    pollInterval: core.pollInterval,
    progress: previous?.progress ?? null,
    progressMessage: previous?.progressMessage ?? "",
    meetingId: core.meetingId ?? previous?.meetingId ?? null,
    error: core.status === "working" ? null : previous?.error ?? null,
  };
}

function publishCore(core: CoreTask): TaskSnapshot {
  const next = snapshotFrom(core, tasks.get(core.taskId));
  tasks.set(core.taskId, next);
  emit();
  // The pending upload request is delivered on tasks/result. A task seen waiting for its
  // upload (after a reload, or polled from another screen) must open it, or it waits forever.
  if (next.status === "input_required") ensureResult(core.taskId);
  return next;
}

function patchTask(taskId: string, patch: Partial<TaskSnapshot>): void {
  const previous = tasks.get(taskId);
  if (!previous) return;
  tasks.set(taskId, { ...previous, ...patch });
  emit();
}

function parseCore(value: unknown): CoreTask | null {
  const record = asRecord(value);
  if (!record) return null;
  const source = asRecord(record.task) ?? record;
  const taskId = asString(source.taskId);
  if (!taskId) return null;
  const poll = asFinite(source.pollInterval);
  return {
    taskId,
    status: asString(source.status) ?? "working",
    statusMessage: asString(source.statusMessage) ?? "",
    pollInterval: poll !== null && poll > 0 ? poll : 1500,
    meetingId: asString(source.meeting_id),
  };
}

function baseHeaders(accept: string): Headers {
  const headers = new Headers();
  headers.set("accept", accept);
  if (sessionId) headers.set(parameters.sessionHeader, sessionId);
  if (initialized) headers.set(parameters.protocolHeader, parameters.protocolVersion);
  return headers;
}

function isDown(status: number): boolean {
  return status === 404 || status === 401 || status === 403 || status >= 500;
}

async function post(payload: unknown, timeoutMs: number): Promise<Response> {
  const headers = baseHeaders("application/json, text/event-stream");
  headers.set("content-type", "application/json");
  try {
    const response = await fetch(parameters.endpointPath, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
    const sid = response.headers.get("mcp-session-id");
    if (sid) sessionId = sid;
    return response;
  } catch (error) {
    if (error instanceof McpDisconnected) throw error;
    throw new McpDisconnected("Quotient MCP is disconnected");
  }
}

function consumeSse(buffer: string): { messages: JsonRpc[]; rest: string } {
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  const messages: JsonRpc[] = [];
  for (const part of parts) {
    const data = part
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).replace(/^ /, ""))
      .join("\n")
      .trim();
    if (!data) continue;
    try {
      messages.push(JSON.parse(data) as JsonRpc);
    } catch {
      continue;
    }
  }
  return { messages, rest };
}

function settle(message: JsonRpc): unknown {
  if (message.error) throw new Error(message.error.message || "MCP request failed");
  return message.result ?? null;
}

async function readUntil(body: ReadableStream<Uint8Array>, id: number, timeoutMs: number): Promise<unknown> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const timer = setTimeout(() => {
    void reader.cancel();
  }, timeoutMs);
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, "\n");
      const consumed = consumeSse(buffer);
      buffer = consumed.rest;
      for (const message of consumed.messages) {
        if (message.method) {
          void handleIncoming(message);
          continue;
        }
        if (message.id === id) return settle(message);
      }
    }
  } finally {
    clearTimeout(timer);
    await reader.cancel().catch(() => undefined);
  }
  throw new Error("MCP stream ended without a result");
}

async function request(method: string, params: unknown, timeoutMs = 20000): Promise<unknown> {
  const id = ++nextId;
  const response = await post({ jsonrpc: "2.0", id, method, params }, timeoutMs);
  if (isDown(response.status)) {
    throw new McpDisconnected(`Quotient MCP is disconnected (${response.status})`);
  }
  const type = response.headers.get("content-type") ?? "";
  if (!type.includes("text/event-stream")) {
    const text = await response.text();
    if (!text) return null;
    try {
      return settle(JSON.parse(text) as JsonRpc);
    } catch (error) {
      if (error instanceof SyntaxError) throw new Error("The service sent an unexpected reply. Please try again.");
      throw error;
    }
  }
  if (!response.body) throw new McpDisconnected("Quotient MCP is disconnected");
  return readUntil(response.body, id, timeoutMs);
}

async function respond(id: number | string, result: unknown): Promise<void> {
  const response = await post({ jsonrpc: "2.0", id, result }, 20000);
  await response.body?.cancel().catch(() => undefined);
  if (isDown(response.status)) throw new McpDisconnected("Quotient MCP is disconnected");
}

function relatedTask(message: JsonRpc): string | null {
  const params = asRecord(message.params);
  const meta = asRecord(params?._meta);
  const related = asRecord(meta?.["io.modelcontextprotocol/related-task"]);
  return asString(related?.taskId);
}

async function stagedOrWait(taskId: string): Promise<File[]> {
  const existing = staged.get(taskId);
  if (existing && existing.length > 0) return existing;
  return new Promise((resolve) => {
    fileWaiters.set(taskId, resolve);
  });
}

// An elicitation arrives on both the notification stream and tasks/result; answer it once.
const answeredElicitations = new Set<string>();

async function onElicitation(taskId: string, rpcId: number | string, params: unknown): Promise<void> {
  const seen = `${taskId}:${String(rpcId)}`;
  if (answeredElicitations.has(seen)) return;
  answeredElicitations.add(seen);
  try {
    const files = await stagedOrWait(taskId);
    patchTask(taskId, { progress: 0, progressMessage: "Uploading the recording" });
    const content = await prepareElicitationContent(params, files, (fraction) => {
      patchTask(taskId, { progress: fraction, progressMessage: `Uploading the recording (${Math.round(fraction * 100)}%)` });
    });
    await respond(rpcId, { action: "accept", content });
    patchTask(taskId, { error: null });
  } catch (error) {
    patchTask(taskId, { error: error instanceof Error ? error.message : "Upload failed" });
  }
}

function handleIncoming(message: JsonRpc): void {
  if (message.method === "elicitation/create" && message.id !== undefined) {
    const taskId = relatedTask(message) ?? activeTaskId;
    if (taskId) void onElicitation(taskId, message.id, message.params);
    return;
  }
  if (message.method === "notifications/tasks/status") {
    const core = parseCore(message.params);
    if (core) publishCore(core);
    return;
  }
  if (message.method === "notifications/progress") {
    const params = asRecord(message.params);
    if (!params) return;
    const token = asString(params.progressToken);
    const taskId = (token && tokenToTask.get(token)) || relatedTask(message) || activeTaskId;
    if (!taskId || !tasks.has(taskId)) return;
    const progress = asFinite(params.progress);
    const total = asFinite(params.total);
    let fraction: number | null = null;
    if (progress !== null && total !== null && total > 0) fraction = progress / total;
    else if (progress !== null && progress >= 0 && progress <= 1) fraction = progress;
    patchTask(taskId, {
      progress: fraction,
      progressMessage: asString(params.message) ?? tasks.get(taskId)?.progressMessage ?? "",
    });
  }
}

async function openChannel(): Promise<void> {
  channel?.abort();
  const controller = new AbortController();
  channel = controller;
  try {
    const response = await fetch(parameters.endpointPath, {
      method: "GET",
      headers: baseHeaders("text/event-stream"),
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok || !response.body) return;
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (!controller.signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, "\n");
      const consumed = consumeSse(buffer);
      buffer = consumed.rest;
      for (const message of consumed.messages) handleIncoming(message);
    }
  } catch {
    // Polling remains the status path when the server has no GET stream.
  }
}

async function connect(): Promise<void> {
  if (phase === "connected") return;
  if (connectPromise) return connectPromise;
  setPhase("connecting", "Contacting POST /mcp");
  connectPromise = (async () => {
    try {
      const init = await request("initialize", {
        protocolVersion: parameters.protocolVersion,
        capabilities: { elicitation: { form: {}, url: {} } },
        clientInfo: { name: "quotient-portal", title: "Quotient", version: "0.1.0" },
      });
      initialized = true;
      const protocol = asString(asRecord(init)?.protocolVersion);
      const noted = await post({ jsonrpc: "2.0", method: "notifications/initialized" }, 10000);
      await noted.body?.cancel().catch(() => undefined);
      const listed = await request("tools/list", {});
      toolNames = new Set(
        asArray(asRecord(listed)?.tools)
          .map((tool) => asString(asRecord(tool)?.name))
          .filter((name): name is string => name !== null),
      );
      setPhase("connected", protocol ? `MCP ${protocol}` : "MCP connected");
      void openChannel();
    } catch (error) {
      initialized = false;
      const message = error instanceof Error ? error.message : "Quotient MCP is disconnected";
      setPhase("disconnected", message);
      throw error instanceof McpDisconnected ? error : new McpDisconnected(message);
    } finally {
      connectPromise = null;
    }
  })();
  return connectPromise;
}

async function ensure(): Promise<void> {
  if (phase !== "connected") await connect();
}

async function callTool(name: string, args: Record<string, unknown>, timeoutMs = 30000): Promise<unknown> {
  await ensure();
  return request("tools/call", { name, arguments: args }, timeoutMs);
}

/**
 * Motivation vs Logic
 * Motivation: Reference material has to reach the analysis before the meeting starts, and one bad
 * file must not stop a meeting.
 * Logic: prepare_context returns a signed target per file. Upload two at a time, each retried once.
 * A failed item is marked and skipped. Returns the batch id when at least one upload landed.
 * A prepare_context failure throws ContextPrepareError and nothing is uploaded.
 */
async function sendContext(context: SubmitContext): Promise<string | null> {
  const uploads = toUploads(context.items);
  if (uploads.length === 0) return null;
  const report = context.onItem ?? (() => undefined);
  let outcome;
  try {
    outcome = parsePrepareResult(await callTool("prepare_context", buildPrepareArgs(uploads)), uploads.length);
  } catch (error) {
    if (error instanceof McpDisconnected) throw error;
    throw new ContextPrepareError(error instanceof Error && error.message ? error.message : "The context could not be prepared.");
  }
  if (!outcome.ok) throw new ContextPrepareError(outcome.error);
  const targets = outcome.uploads;
  let succeeded = 0;
  await runPool(uploads, UPLOAD_CONCURRENCY, async (upload, index) => {
    const target = targets[index];
    if (!target) {
      report(upload.id, { status: "failed", reason: "Couldn't upload" });
      return;
    }
    for (let attempt = 0; attempt < 2; attempt += 1) {
      report(upload.id, { status: "uploading", progress: 0, reason: "" });
      try {
        await putFile(target.url, upload.file, target.headers, (fraction) => report(upload.id, { status: "uploading", progress: fraction }));
        report(upload.id, { status: "ready", progress: 1 });
        succeeded += 1;
        return;
      } catch {
        // One more try, then the item is skipped.
      }
    }
    report(upload.id, { status: "failed", reason: "Couldn't upload" });
  });
  return succeeded > 0 ? outcome.batchId : null;
}

function ensureResult(taskId: string): void {
  if (resultWaiters.has(taskId)) return;
  resultWaiters.add(taskId);
  const existing = resultPromises.get(taskId);
  const promise = existing ?? readTaskResult(taskId);
  if (!existing) resultPromises.set(taskId, promise);
  void promise.then(
    (result) => {
      const meetingId = parseMeetingId(result);
      const current = tasks.get(taskId);
      if (meetingId) {
        patchTask(taskId, { meetingId });
        const file = staged.get(taskId)?.[0];
        // Keep the name the user typed at submit; fall back to the file name only when no row has one.
        const known = readLibrary().find((row) => row.taskId === taskId);
        upsertLibrary({
          meetingId,
          taskId,
          title: known?.title || file?.name || meetingId,
          filename: file?.name ?? "",
          status: current?.status ?? "completed",
          reviewCount: null,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        });
      }
    },
    (error) => {
      resultPromises.delete(taskId);
      resultWaiters.delete(taskId);
      patchTask(taskId, { error: error instanceof Error ? error.message : "The task result failed" });
    },
  );
}

async function readTaskResult(taskId: string): Promise<unknown> {
  const id = ++nextId;
  const response = await post({ jsonrpc: "2.0", id, method: "tasks/result", params: { taskId } }, 86_400_000);
  if (isDown(response.status)) throw new McpDisconnected("Quotient MCP is disconnected");
  const type = response.headers.get("content-type") ?? "";
  if (!type.includes("text/event-stream")) {
    const text = await response.text();
    if (!text) return null;
    return settle(JSON.parse(text) as JsonRpc);
  }
  if (!response.body) throw new McpDisconnected("Quotient MCP is disconnected");
  return readUntil(response.body, id, 86_400_000);
}

function watchTask(taskId: string): void {
  if (watches.has(taskId)) return;
  watches.add(taskId);
  let timer: ReturnType<typeof setTimeout> | null = null;
  const tick = async () => {
    try {
      const result = await request("tasks/get", { taskId }, 20000);
      const core = parseCore(result);
      if (!core) throw new Error("tasks/get returned no task");
      const snapshot = publishCore(core);
      if (snapshot.status === "input_required" || snapshot.status === "completed") ensureResult(taskId);
      if (snapshot.status === "failed" || snapshot.status === "cancelled" || snapshot.status === "completed") {
        watches.delete(taskId);
        return;
      }
      timer = setTimeout(() => void tick(), snapshot.pollInterval);
    } catch (error) {
      if (error instanceof McpDisconnected) {
        setPhase("disconnected", error.message);
        patchTask(taskId, { error: error.message });
        watches.delete(taskId);
        return;
      }
      timer = setTimeout(() => void tick(), 2000);
    }
  };
  void tick();
  void timer;
}

export const mcp = {
  phase(): Phase {
    return phase;
  },
  detail(): string {
    return detail;
  },
  parameters(): typeof parameters {
    return parameters;
  },
  getSessionId(): string | null {
    return sessionId;
  },
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  connect,
  reset(): void {
    channel?.abort();
    channel = null;
    sessionId = null;
    initialized = false;
    connectPromise = null;
    toolNames = new Set();
    setPhase("idle", "POST /mcp has not been contacted yet");
  },
  hasTool(name: string): boolean {
    return toolNames.has(name);
  },
  taskSnapshot(taskId: string): TaskSnapshot | null {
    return tasks.get(taskId) ?? null;
  },
  attachFiles(taskId: string, files: File[]): void {
    staged.set(taskId, files);
    const waiter = fileWaiters.get(taskId);
    if (waiter) {
      fileWaiters.delete(taskId);
      waiter(files);
    }
    emit();
  },
  stagedFiles(taskId: string): File[] {
    return staged.get(taskId) ?? [];
  },
  async submitMeeting(primary: File, others: File[], title: string, context?: SubmitContext): Promise<TaskSnapshot> {
    await ensure();
    // Reference material goes first; if it cannot be prepared, no meeting is started.
    const contextBatch = context ? await sendContext(context) : null;
    const purpose = context?.purpose.trim() ?? "";
    const token = `submit:${primary.size}:${nextId + 1}`;
    const result = await request("tools/call", {
      name: "submit_meeting",
      arguments: {
        // An empty key asks the server for a signed upload target (input_required).
        object_key: "",
        upload_complete: false,
        filename: primary.name,
        media_type: mediaTypeOf(primary),
        byte_size: primary.size,
        ...(contextBatch ? { context_batch: contextBatch } : {}),
        ...(purpose ? { purpose } : {}),
      },
      task: { ttl: 86_400_000 },
      _meta: { progressToken: token },
    });
    const core = parseCore(result);
    if (!core) throw new Error("submit_meeting did not return a task");
    activeTaskId = core.taskId;
    tokenToTask.set(token, core.taskId);
    // Bugs vs Fixes
    // Bug: The upload elicitation can arrive on the stream before this call returns. Its
    // handler then waited for files, and storing them here never woke it, so the upload
    // never started unless the user picked the file again.
    // Fix: Stage through attachFiles, which also resolves a waiting handler.
    mcp.attachFiles(core.taskId, [primary, ...others]);
    const snapshot = publishCore(core);
    const now = new Date().toISOString();
    // A name the person typed differs from the one the file name would give; it is theirs from the start.
    const fromFile = primary.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
    upsertLibrary({
      meetingId: snapshot.meetingId,
      taskId: snapshot.taskId,
      title,
      renamed: title !== fromFile,
      filename: primary.name,
      status: snapshot.status,
      reviewCount: null,
      createdAt: now,
      updatedAt: now,
    });
    watchTask(snapshot.taskId);
    if (snapshot.status === "input_required") ensureResult(snapshot.taskId);
    return snapshot;
  },
  watchTask,
  async cancelTask(taskId: string): Promise<void> {
    await ensure();
    const result = await request("tasks/cancel", { taskId });
    const core = parseCore(result);
    if (core) publishCore(core);
    watches.delete(taskId);
  },
  async listMeetingIds(): Promise<string[]> {
    await ensure();
    const ids = new Set<string>();
    let cursor: string | undefined;
    for (let page = 0; page < 20; page += 1) {
      const result = await request("resources/list", cursor ? { cursor } : {});
      const record = asRecord(result);
      for (const resource of asArray(record?.resources)) {
        const uri = asString(asRecord(resource)?.uri);
        const id = uri ? meetingIdFromUri(uri) : null;
        if (id) ids.add(id);
      }
      const next = asString(record?.nextCursor);
      if (!next) break;
      cursor = next;
    }
    return [...ids];
  },
  async getMeeting(meetingId: string): Promise<MeetingStatus> {
    const result = await callTool("get_meeting", { meeting_id: meetingId });
    return parseMeetingStatus(result, meetingId);
  },
  async readGraph(meetingId: string): Promise<GraphPage> {
    let cursor: string | undefined;
    let merged = emptyGraph();
    for (let page = 0; page < 50; page += 1) {
      const args: Record<string, unknown> = { meeting_id: meetingId };
      if (cursor) args.cursor = cursor;
      const result = await callTool("read_graph", args);
      const parsed = parseGraph(unwrapTool(result), meetingId);
      merged = mergeGraph(merged, parsed);
      if (!parsed.next_cursor || parsed.next_cursor === cursor) break;
      cursor = parsed.next_cursor;
    }
    return merged;
  },
  async readSpan(meetingId: string, spanId: string) {
    const result = await callTool("read_span", { meeting_id: meetingId, span_id: spanId });
    const unwrapped = unwrapTool(result);
    const record = asRecord(unwrapped);
    const raw = record?.spans ?? record?.span ?? record;
    const page = parseGraph({ spans: Array.isArray(raw) ? raw : raw ? [raw] : [] }, meetingId);
    return page.spans.find((span) => span.id === spanId) ?? page.spans[0] ?? null;
  },
  async acceptAction(meetingId: string, actionId: string): Promise<void> {
    await callTool("accept_action", { meeting_id: meetingId, action_id: actionId });
  },
  async reviseSpeaker(meetingId: string, spanId: string, scope: "span" | "hypothesis", displayName: string): Promise<void> {
    await callTool("revise_speaker", {
      meeting_id: meetingId,
      span_id: spanId,
      scope,
      display_name: displayName,
    });
  },
  async mergeSpeakers(meetingId: string, spanId: string, otherSpanId: string, displayName: string): Promise<void> {
    await callTool("merge_speakers", {
      meeting_id: meetingId,
      span_id: spanId,
      other_span_id: otherSpanId,
      display_name: displayName,
    });
  },
  async reviseText(meetingId: string, spanId: string, text: string): Promise<void> {
    await callTool("revise_text", { meeting_id: meetingId, span_id: spanId, text });
  },
  async cancelMeeting(meetingId: string): Promise<void> {
    await callTool("cancel_meeting", { meeting_id: meetingId });
  },
  /**
   * Motivation vs Logic
   * Motivation: The MCP screen has to show the live catalog, not a copied list.
   * Logic: tools/list is read-only. Name, title, description, and inputSchema
   * are passed through. A missing field stays empty.
   */
  async listTools(): Promise<ToolCatalog[]> {
    await ensure();
    const result = await request("tools/list", {});
    return asArray(asRecord(result)?.tools).flatMap((item) => {
      const record = asRecord(item);
      const name = asString(record?.name);
      if (!name) return [];
      return [{
        name,
        title: asString(record?.title) ?? "",
        description: asString(record?.description) ?? "",
        inputSchema: asRecord(record?.inputSchema),
      }];
    });
  },
  async listSkills(): Promise<SkillSummary[]> {
    await ensure();
    const result = await request("prompts/list", {});
    return asArray(asRecord(result)?.prompts).flatMap((item) => {
      const record = asRecord(item);
      const name = asString(record?.name);
      if (!name) return [];
      return [{
        name,
        title: asString(record?.title) ?? name,
        description: asString(record?.description) ?? "",
      }];
    });
  },
  async readSkill(name: string): Promise<string> {
    await ensure();
    const result = await request("prompts/get", { name });
    const parts: string[] = [];
    for (const message of asArray(asRecord(result)?.messages)) {
      const content = asRecord(message)?.content;
      const text = asString(asRecord(content)?.text) ?? asString(content);
      if (text) parts.push(text);
    }
    return parts.join("\n\n");
  },
  async readResource(uri: string): Promise<{ filename: string; mimeType: string; blob: Blob | null; href: string | null }> {
    await ensure();
    const result = await request("resources/read", { uri }, 120000);
    const contents = asArray(asRecord(result)?.contents);
    const first = asRecord(contents[0]);
    if (!first) throw new Error("The resource was empty");
    const mimeType = asString(first.mimeType) ?? "application/octet-stream";
    const filename = uri.slice(uri.lastIndexOf("/") + 1) || "export";
    const text = asString(first.text);
    if (text && (text.startsWith("https://") || text.startsWith("http://"))) {
      return { filename, mimeType, blob: null, href: text };
    }
    if (typeof first.blob === "string") {
      const bytes = Uint8Array.from(atob(first.blob), (char) => char.charCodeAt(0));
      return { filename, mimeType, blob: new Blob([bytes], { type: mimeType }), href: null };
    }
    if (text !== null) {
      return { filename, mimeType, blob: new Blob([text], { type: mimeType }), href: null };
    }
    throw new Error("The resource had no body");
  },
};
