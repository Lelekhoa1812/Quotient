/**
 * Motivation vs Logic
 * Motivation: The portal must call MCP on the same origin as the page. A second
 * meetings REST surface would break the partner contract.
 * Logic: Rewrite only `/mcp` to the Quotient MCP server. The `@` alias is set
 * on the bundler so App Router imports resolve from this package root.
 *
 * Bugs vs Fixes
 * Bug: app/mcp/page.tsx matches /mcp, so an afterFiles rewrite never ran and
 * the portal client received the contract page instead of MCP.
 * Fix: beforeFiles rewrite when Accept carries text/event-stream. A browser
 * navigation still renders the contract page.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));
const mcp = process.env.QUOTIENT_MCP_URL ?? "http://127.0.0.1:8080/mcp";

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Keep live development output separate from production builds. `next build`
  // otherwise replaces files the running `next dev` process is serving.
  distDir: process.env.QUOTIENT_NEXT_DIST_DIR ?? (process.env.NODE_ENV === "development" ? ".next-dev" : ".next"),
  poweredByHeader: false,
  eslint: { ignoreDuringBuilds: true },
  webpack(config) {
    config.resolve.alias = {
      ...config.resolve.alias,
      "@/components": path.join(root, "components"),
      "@/lib": path.join(root, "lib"),
    };
    return config;
  },
  async rewrites() {
    return {
      beforeFiles: [
        {
          source: "/mcp",
          has: [{ type: "header", key: "accept", value: "(application/json, )?text/event-stream" }],
          destination: mcp,
        },
      ],
    };
  },
};

export default nextConfig;
