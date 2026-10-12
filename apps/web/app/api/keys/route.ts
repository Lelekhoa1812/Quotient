/**
 * Motivation vs Logic
 * Motivation: Settings has to show, copy, and revoke the integration key, and
 * the browser must not talk to the API port directly for that.
 * Logic: Loopback and same-origin checks match the settings route. This route
 * then calls the local API, which only accepts key admin from this computer.
 */
import { NextResponse } from "next/server";
import { safeToMutate } from "@/lib/guard";
import { deployment, runtimeEnv } from "@/lib/site";

export const dynamic = "force-dynamic";

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

async function forward(path: string, method: "GET" | "POST") {
  const headers: Record<string, string> = {};
  const token = runtimeEnv("QUOTIENT_PORTAL_TOKEN");
  if (token) headers["X-Quotient-Portal"] = token;
  const origin = runtimeEnv("QUOTIENT_API_ORIGIN") || "http://127.0.0.1:8080";
  try {
    const response = await fetch(`${origin}${path}`, { method, headers, cache: "no-store" });
    const body = await response.json() as unknown;
    return NextResponse.json(body, { status: response.status });
  } catch {
    return NextResponse.json({ error: "Quotient could not be reached." }, { status: 503 });
  }
}

export async function GET(request: Request) {
  if (!siteRequest(request)) {
    return NextResponse.json({ error: "API keys can be changed on this computer only." }, { status: 403 });
  }
  return forward("/v1/keys", "GET");
}

export async function POST(request: Request) {
  if (!siteRequest(request)) {
    return NextResponse.json({ error: "API keys can be changed on this computer only." }, { status: 403 });
  }
  if (!safeToMutate(request.headers, deployment())) {
    return NextResponse.json({ error: "This request did not come from the Quotient settings page." }, { status: 403 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "The request could not be read." }, { status: 400 });
  }
  const action = body && typeof body === "object" && !Array.isArray(body) ? (body as { action?: unknown }).action : null;
  if (action === "revoke") return forward("/v1/keys/revoke", "POST");
  if (action === "issue") return forward("/v1/keys", "POST");
  return NextResponse.json({ error: "The request could not be read." }, { status: 400 });
}
