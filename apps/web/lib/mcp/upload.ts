/**
 * Motivation vs Logic
 * Motivation: submit_meeting is task-backed. An incomplete upload arrives as
 * elicitation on the task, not as a meetings REST call.
 * Logic: Read an http(s) target from the elicitation params, PUT the staged
 * file or its parts, and return only schema fields the portal can fill from
 * the file metadata.
 */

import { asArray, asFinite, asRecord, asString } from "@/lib/json";

type Part = {
  url: string;
  part_number: number;
  offset: number | null;
  length: number | null;
};

type UploadTarget = {
  url: string;
  method: string;
  headers: Record<string, string>;
  parts: Part[];
  objectKey: string | null;
};

export type UploadProgress = (fraction: number) => void;

const EXTENSION_TYPES: Record<string, string> = {
  mp4: "video/mp4",
  m4v: "video/mp4",
  mov: "video/quicktime",
  webm: "video/webm",
  mkv: "video/x-matroska",
  mp3: "audio/mpeg",
  m4a: "audio/mp4",
  aac: "audio/aac",
  wav: "audio/wav",
  flac: "audio/flac",
  ogg: "audio/ogg",
  opus: "audio/ogg",
};

/** The file's media type, falling back to its extension when the browser does not know it. */
export function mediaTypeOf(file: File): string {
  if (file.type && /^(audio|video)\//.test(file.type)) return file.type;
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return EXTENSION_TYPES[extension] ?? (file.type || "application/octet-stream");
}

export async function prepareElicitationContent(
  params: unknown,
  files: File[],
  onProgress?: UploadProgress,
): Promise<Record<string, unknown>> {
  const file = pickFile(params, files);
  const target = findUpload(params);
  let uploaded = false;
  const parts: { part_number: number; etag: string | null }[] = [];
  if (file && target) {
    if (target.parts.length > 0) {
      for (const part of target.parts) {
        const slice = slicePart(file, part, target.parts);
        const etag = await putBytes(part.url, slice, mediaTypeOf(file), target.headers, target.method);
        parts.push({ part_number: part.part_number, etag });
      }
      uploaded = true;
    } else if (isHttp(target.url)) {
      await putBytes(target.url, file, mediaTypeOf(file), target.headers, target.method, onProgress);
      uploaded = true;
    }
  }
  return contentForSchema(asRecord(params)?.requestedSchema, file, uploaded, parts, target?.objectKey ?? null);
}

function pickFile(params: unknown, files: File[]): File | null {
  const wanted = asString(asRecord(params)?.filename);
  if (wanted) {
    const match = files.find((file) => file.name === wanted);
    if (match) return match;
  }
  return files[0] ?? null;
}

function findUpload(params: unknown): UploadTarget | null {
  const root = asRecord(params);
  if (!root) return null;
  const meta = asRecord(root._meta);
  const buckets = [asRecord(root.upload), asRecord(meta?.upload), meta, root].filter(
    (bucket): bucket is Record<string, unknown> => bucket !== null,
  );
  for (const bucket of buckets) {
    const parts = parseParts(bucket.parts);
    const explicit = asString(bucket.upload_url);
    const modeUrl = bucket === root && root.mode === "url" ? asString(root.url) : null;
    const nestedUrl = bucket !== root ? asString(bucket.url) : null;
    const url = [explicit, modeUrl, nestedUrl].find((item) => item && isHttp(item)) ?? "";
    if (parts.length === 0 && !url) continue;
    return {
      url,
      method: (asString(bucket.method) ?? "PUT").toUpperCase(),
      headers: stringMap(bucket.headers),
      parts,
      objectKey: asString(bucket.object_key),
    };
  }
  return null;
}

function parseParts(value: unknown): Part[] {
  const parts: Part[] = [];
  for (const item of asArray(value)) {
    const record = asRecord(item);
    const url = asString(record?.url);
    const partNumber = asFinite(record?.part_number);
    if (!record || !url || !isHttp(url) || partNumber === null) continue;
    parts.push({
      url,
      part_number: partNumber,
      offset: asFinite(record.offset),
      length: asFinite(record.length),
    });
  }
  return parts;
}

function slicePart(file: File, part: Part, parts: Part[]): Blob {
  if (part.offset !== null && part.length !== null) {
    return file.slice(part.offset, part.offset + part.length);
  }
  const index = Math.max(0, parts.findIndex((item) => item.part_number === part.part_number));
  const size = Math.ceil(file.size / parts.length);
  const start = index * size;
  return file.slice(start, Math.min(file.size, start + size));
}

/** PUT one file to a signed URL with exactly the headers the service returned, reporting progress. */
export function putFile(url: string, body: Blob, headers: Record<string, string>, onProgress?: UploadProgress): Promise<void> {
  return putBytes(url, body, body.type, headers, "PUT", onProgress).then(() => undefined);
}

function putBytes(
  url: string,
  body: Blob,
  type: string,
  headers: Record<string, string>,
  method: string,
  onProgress?: UploadProgress,
): Promise<string | null> {
  // XMLHttpRequest, not fetch, because only it reports upload progress.
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open(method, url);
    let typed = false;
    for (const [key, value] of Object.entries(headers)) {
      request.setRequestHeader(key, value);
      if (key.toLowerCase() === "content-type") typed = true;
    }
    if (!typed) request.setRequestHeader("Content-Type", type || "application/octet-stream");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) resolve(request.getResponseHeader("etag"));
      else reject(new Error(`Upload failed (${request.status})`));
    };
    // A connection that stalls without an error would otherwise hold the whole submission forever.
    request.timeout = 120_000 + Math.ceil(body.size / 20);
    request.ontimeout = () => reject(new Error("The upload took too long"));
    request.onerror = () => reject(new Error("The upload URL did not accept the file"));
    request.onabort = () => reject(new Error("The upload was cancelled"));
    request.send(body);
  });
}

function contentForSchema(
  schema: unknown,
  file: File | null,
  uploaded: boolean,
  parts: { part_number: number; etag: string | null }[],
  objectKey: string | null,
): Record<string, unknown> {
  const facts = fileFacts(file, uploaded, parts, objectKey);
  const properties = asRecord(asRecord(schema)?.properties);
  if (!properties) return facts;
  const keys = Object.keys(properties);
  if (keys.length === 0) return facts;
  const content: Record<string, unknown> = {};
  for (const key of keys) {
    if (key in facts) content[key] = facts[key];
  }
  return content;
}

function fileFacts(
  file: File | null,
  uploaded: boolean,
  parts: { part_number: number; etag: string | null }[],
  objectKey: string | null,
): Record<string, unknown> {
  if (!file) return { uploaded, upload_complete: false };
  return {
    // The server minted this key; it accepts completion only for it.
    ...(objectKey ? { object_key: objectKey } : {}),
    upload_complete: uploaded,
    filename: file.name,
    name: file.name,
    media_type: mediaTypeOf(file),
    mime_type: mediaTypeOf(file),
    content_type: mediaTypeOf(file),
    byte_size: file.size,
    size: file.size,
    uploaded,
    parts,
  };
}

function stringMap(value: unknown): Record<string, string> {
  const record = asRecord(value);
  if (!record) return {};
  const headers: Record<string, string> = {};
  for (const [key, item] of Object.entries(record)) {
    if (typeof item === "string") headers[key] = item;
  }
  return headers;
}

/** https, or plain http only to this machine (local object storage): a document must not cross a network in clear text. */
function isHttp(url: string): boolean {
  if (url.startsWith("https://")) return true;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
  } catch {
    return false;
  }
}
