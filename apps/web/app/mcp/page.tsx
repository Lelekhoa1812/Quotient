/**
 * Motivation vs Logic
 * Motivation: The partner contract is a local file. It has to stay readable
 * when the MCP server is down.
 * Logic: Read MCP.md from the repo root, two levels above this app, and pass
 * the raw string to the client screen. No MCP call is involved.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";
import type { Metadata } from "next";
import { McpScreen } from "@/components/mcp";
import "./mcp.css";

export const metadata: Metadata = { title: "MCP" };

export default async function Page() {
  const contract = await readFile(path.join(process.cwd(), "../../MCP.md"), "utf8");
  return <McpScreen contract={contract} />;
}
