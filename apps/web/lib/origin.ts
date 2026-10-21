/**
 * Motivation vs Logic
 * Motivation: Pages were compiled with http://127.0.0.1:8080, so a deployed
 * portal kept showing the developer machine.
 * Logic: Loopback keeps that local API. Any other host uses the page origin,
 * which on staging is the load balancer.
 */

const LOCAL_API = "http://127.0.0.1:8080";

export const STAGING_CLOUDFRONT_DOMAIN = "d13b140h08qjom.cloudfront.net";
export const STAGING_HTTPS_MCP_URL = `https://${STAGING_CLOUDFRONT_DOMAIN}/mcp`;
export const STAGING_ALB_DOMAIN = "axion-meeting-staging-315925467.ap-southeast-2.elb.amazonaws.com";
export const STAGING_HTTP_MCP_URL = `http://${STAGING_ALB_DOMAIN}/mcp`;

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

export function httpsMcpUrl(location?: { hostname: string; origin: string } | null, fallback?: string): string {
  if (fallback && fallback.startsWith("https://")) return fallback;
  if (location && location.origin.startsWith("https://")) return `${location.origin}/mcp`;
  return STAGING_HTTPS_MCP_URL;
}

export function httpMcpUrl(location?: { hostname: string; origin: string } | null, fallback?: string): string {
  if (fallback && fallback.startsWith("http://") && !fallback.startsWith("https://")) return fallback;
  if (location && localHost(location.hostname)) return `${LOCAL_API}/mcp`;
  if (location && location.origin.startsWith("http://") && !location.origin.startsWith("https://")) {
    return `${location.origin}/mcp`;
  }
  return STAGING_HTTP_MCP_URL;
}
