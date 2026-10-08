/**
 * Motivation vs Logic
 * Motivation: /api/settings rewrites the .env file that holds the model credentials. Any web
 * page the developer visits could POST to http://127.0.0.1:3000 with a "simple" request
 * (text/plain, no preflight); the Host check alone passes because the browser sends the
 * loopback Host.
 * Logic: A state-changing request must come from this portal itself: its Origin is absent
 * (non-browser client on this machine) or equals the request's own loopback origin, and its
 * body is application/json, which browsers cannot send cross-site without a preflight.
 */

const LOOPBACK = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);

export function hostName(host: string): string {
  const value = host.trim().toLowerCase();
  if (value.startsWith("[")) return value.slice(0, value.indexOf("]") + 1);
  return value.split(":")[0] ?? "";
}

export function trustedOrigin(origin: string | null, host: string): boolean {
  if (origin === null || origin === "") return true;
  let parsed: URL;
  try {
    parsed = new URL(origin);
  } catch {
    return false;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
  return LOOPBACK.has(hostName(parsed.host)) && parsed.host.toLowerCase() === host.trim().toLowerCase();
}

export function jsonContent(contentType: string | null): boolean {
  return (contentType ?? "").toLowerCase().split(";")[0]?.trim() === "application/json";
}

export function safeToMutate(headers: Headers): boolean {
  return trustedOrigin(headers.get("origin"), headers.get("host") ?? "") && jsonContent(headers.get("content-type"));
}
