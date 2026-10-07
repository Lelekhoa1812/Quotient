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
};

export async function prepareElicitationContent(params: unknown, files: File[]): Promise<Record<string, unknown>> {
  const file = pickFile(params, files);
  const target = findUpload(params);
  let uploaded = false;
  const parts: { part_number: number; etag: string | null }[] = [];
  if (file && target) {
    if (target.parts.length > 0) {
      for (const part of target.parts) {
        const slice = slicePart(file, part, target.parts);
        const etag = await putBytes(part.url, slice, file.type, target.headers, target.method);
        parts.push({ part_number: part.part_number, etag });
      }
      uploaded = true;
    } else if (isHttp(target.url)) {
      await putBytes(target.url, file, file.type, target.headers, target.method);
      uploaded = true;
    }
  }
  return contentForSchema(asRecord(params)?.requestedSchema, file, uploaded, parts);
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

async function putBytes(
  url: string,
  body: Blob,
  type: string,
  headers: Record<string, string>,
  method: string,
): Promise<string | null> {
  const requestHeaders = new Headers(headers);
  if (!requestHeaders.has("content-type")) {
    requestHeaders.set("content-type", type || "application/octet-stream");
  }
  let response: Response;
  try {
    response = await fetch(url, { method, body, headers: requestHeaders });
  } catch {
    throw new Error("The upload URL did not accept the file");
  }
  if (!response.ok) throw new Error(`Upload failed (${response.status})`);
  return response.headers.get("etag");
}

function contentForSchema(
  schema: unknown,
  file: File | null,
  uploaded: boolean,
  parts: { part_number: number; etag: string | null }[],
): Record<string, unknown> {
  const facts = fileFacts(file, uploaded, parts);
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
): Record<string, unknown> {
  if (!file) return { uploaded };
  return {
    filename: file.name,
    name: file.name,
    media_type: file.type || "application/octet-stream",
    mime_type: file.type || "application/octet-stream",
    content_type: file.type || "application/octet-stream",
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

function isHttp(url: string): boolean {
  return url.startsWith("https://") || url.startsWith("http://");
}
