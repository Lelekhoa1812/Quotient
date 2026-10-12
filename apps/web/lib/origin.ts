/**
 * Motivation vs Logic
 * Motivation: Pages were compiled with http://127.0.0.1:8080, so a deployed
 * portal kept showing the developer machine.
 * Logic: Loopback keeps that local API. Any other host uses the page origin,
 * which on staging is the load balancer.
 */

const LOCAL_API = "http://127.0.0.1:8080";

export function localHost(hostname: string): boolean {
  const host = hostname.trim().toLowerCase();
  return host === "localhost" || host === "127.0.0.1" || host === "[::1]" || host === "::1";
}

export function apiBase(location: { hostname: string; origin: string } | null): string {
  if (!location || localHost(location.hostname) || !location.origin) return LOCAL_API;
  return location.origin;
}

export function apiMcpUrl(location: { hostname: string; origin: string } | null): string {
  return `${apiBase(location)}/mcp`;
}
