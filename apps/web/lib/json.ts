/**
 * Motivation vs Logic
 * Motivation: MCP tool results arrive as loosely typed JSON. The portal has to
 * read them without embedding a registry schema or guessing from prose.
 * Logic: Narrow with typeof checks. Callers drop values that are not the
 * expected JSON kind.
 */

export function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function asFinite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function stringList(value: unknown): string[] {
  const found: string[] = [];
  for (const item of asArray(value)) {
    if (typeof item === "string" && item.length > 0) found.push(item);
  }
  return found;
}
