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
import { applyEnv, isSettingKey, readEnvValues, safeSettingValue, SETTINGS, settingField } from "@/lib/settings";

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

export async function GET(request: Request) {
  if (!localRequest(request)) {
    return NextResponse.json({ local: false, fields: [] }, { status: 403 });
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
        set: Boolean(values[field.key]),
        value: field.secret ? "" : (values[field.key] ?? ""),
      })),
    });
  } catch {
    return NextResponse.json({ local: true, error: "The environment file could not be read." }, { status: 500 });
  }
}

export async function POST(request: Request) {
  if (!localRequest(request)) {
    return NextResponse.json({ error: "Settings can be changed on this computer only." }, { status: 403 });
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
    if (!isSettingKey(key) || typeof raw !== "string") {
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
