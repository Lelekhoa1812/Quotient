/**
 * Motivation vs Logic
 * Motivation: The HTTP contract is a local file. It has to stay readable when
 * the API process is down.
 * Logic: Read API.md from the repo root, two levels above this app, and pass
 * the raw string to the client screen. No API call is involved.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";
import type { Metadata } from "next";
import { ApiScreen } from "@/components/guide";
import "../mcp/mcp.css";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "API" };

export default async function Page() {
  const contract = await readFile(path.join(process.cwd(), "../../API.md"), "utf8");
  return <ApiScreen contract={contract} />;
}
