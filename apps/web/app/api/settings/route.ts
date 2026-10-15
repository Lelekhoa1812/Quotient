/**
 * Motivation vs Logic
 * Motivation: API keys and model names live in the local environment file.
 * The browser must be able to change them without ever receiving a secret.
 * Logic: GET returns labels, whether a secret is present, and non-secret
 * values. POST replaces only allowlisted keys. Loopback requests only.
 */
import { readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";
import { safeToMutate } from "@/lib/guard";
import { applyEnv, isEditableKey, isSettingKey, readEnvValues, safeSettingValue, SETTINGS, settingField } from "@/lib/settings";
import { deployment } from "@/lib/site";

const RELEASE: Record<string, string> = {
  AWS_BEDROCK_TRANSCRIBE: "amazon.nova-2-5-sonic",
  AWS_BEDROCK_TRANSCRIBE_REGION: "ap-northeast-1",
  AWS_BEDROCK_MEETING: "global.twelvelabs.pegasus-1-5-v1:0",
  AWS_BEDROCK_LLM: "global.openai.gpt-6.1-sol",
  AWS_BEDROCK_SLM: "global.openai.gpt-6-luna",
};

export const dynamic = "force-dynamic";

function envPath(): string {
  return path.resolve(process.cwd(), "../../.env");
}

function loopbackHost(value: string): boolean {
  const host = value.toLowerCase();
  return host.startsWith("127.0.0.1:") || host.startsWith("localhost:") || host.startsWith("[::1]") || host === "127.0.0.1" || host === "localhost" || host === "[::1]" || host === "::1";
}

function localRequest(request: Request): boolean {
  if (!loopbackHost(request.headers.get("host") ?? "")) return false;
  const forwarded = request.headers.get("x-forwarded-for");
  if (!forwarded) return true;
  const first = forwarded.split(",")[0]?.trim() ?? "";
  return first === "127.0.0.1" || first === "::1" || first === "localhost";
}

function siteRequest(request: Request): boolean {
  if (deployment()) return Boolean((request.headers.get("host") ?? "").trim());
  return localRequest(request);
}

function releaseFields() {
  return SETTINGS.filter((field) => !field.secret).map((field) => ({
    key: field.key,
    label: field.label,
    secret: field.secret,
    group: field.group,
    editable: false,
    set: Boolean(RELEASE[field.key]),
    value: RELEASE[field.key] ?? "",
  }));
}

export async function GET(request: Request) {
  if (!siteRequest(request)) {
    return NextResponse.json({ local: false, fields: [] }, { status: 403 });
  }
  if (deployment()) {
    return NextResponse.json({ local: true, deployment: true, fields: releaseFields() });
  }
  try {
    const text = await readFile(envPath(), "utf8");
    const values = readEnvValues(text, SETTINGS.map((field) => field.key));
    return NextResponse.json({
      local: true,
      fields: SETTINGS.map((field) => ({
        key: field.key,
        label: field.label,
        secret: field.secret,
        group: field.group,
        editable: field.editable,
        set: Boolean(values[field.key]),
        value: field.secret ? "" : (values[field.key] ?? ""),
      })),
    });
  } catch {
    return NextResponse.json({ local: true, error: "The environment file could not be read." }, { status: 500 });
  }
}

export async function POST(request: Request) {
  if (!siteRequest(request)) {
    return NextResponse.json({ error: "Settings can be changed on this computer only." }, { status: 403 });
  }
  const shared = deployment();
  if (!safeToMutate(request.headers, shared)) {
    return NextResponse.json({ error: "This request did not come from the Quotient settings page." }, { status: 403 });
  }
  if (shared) {
    return NextResponse.json({ saved: true, deployment: true });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "The settings could not be read." }, { status: 400 });
  }
  const values = body && typeof body === "object" && !Array.isArray(body) ? (body as { values?: unknown }).values : null;
  if (!values || typeof values !== "object" || Array.isArray(values)) {
    return NextResponse.json({ error: "The settings could not be read." }, { status: 400 });
  }
  const updates: Record<string, string> = {};
  for (const [key, raw] of Object.entries(values)) {
    if (!isSettingKey(key) || !isEditableKey(key) || typeof raw !== "string") {
      return NextResponse.json({ error: "One of the fields is not recognised." }, { status: 400 });
    }
    const field = settingField(key);
    const value = raw.trim();
    if (!value) {
      if (field?.secret) continue;
      return NextResponse.json({ error: `${field?.label ?? "A field"} is required.` }, { status: 400 });
    }
    if (!safeSettingValue(value)) {
      return NextResponse.json({ error: `${field?.label ?? "A field"} has a character this file cannot store.` }, { status: 400 });
    }
    updates[key] = value;
  }
  const file = envPath();
  try {
    const text = await readFile(file, "utf8");
    const next = applyEnv(text, updates);
    const temp = `${file}.tmp`;
    await writeFile(temp, next, { mode: 0o600 });
    await rename(temp, file);
  } catch {
    return NextResponse.json({ error: "The environment file could not be saved." }, { status: 500 });
  }
  return NextResponse.json({ saved: true });
}
