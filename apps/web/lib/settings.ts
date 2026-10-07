/**
 * Motivation vs Logic
 * Motivation: The portal needs a fixed set of local options. Secret values
 * must never be part of that catalog's public shape.
 * Logic: Names, labels, and the secret flag live here. The route reads and
 * writes the environment file. Callers send a secret only when replacing it.
 */

export type SettingField = {
  key: string;
  label: string;
  secret: boolean;
  group: "Keys" | "Models";
};

export const SETTINGS: SettingField[] = [
  { key: "AWS_BEDROCK_API_KEY", label: "Bedrock API key", secret: true, group: "Keys" },
  { key: "JEV_TYPESAFE_API_KEY", label: "TypeSafe API key", secret: true, group: "Keys" },
  { key: "AWS_BEDROCK_TRANSCRIBE", label: "Transcription model", secret: false, group: "Models" },
  { key: "AWS_BEDROCK_TRANSCRIBE_REGION", label: "Transcription region", secret: false, group: "Models" },
  { key: "AWS_BEDROCK_MEETING", label: "Meeting model", secret: false, group: "Models" },
  { key: "AWS_BEDROCK_LLM", label: "Language model", secret: false, group: "Models" },
  { key: "AWS_BEDROCK_SLM", label: "Smaller model", secret: false, group: "Models" },
];

const ALLOWED = new Set(SETTINGS.map((field) => field.key));

export function isSettingKey(key: string): boolean {
  return ALLOWED.has(key);
}

export function settingField(key: string): SettingField | undefined {
  return SETTINGS.find((field) => field.key === key);
}

export function safeSettingValue(value: string): boolean {
  return value.length > 0 && value.length <= 4096 && /^[^\s"'#]+$/.test(value);
}

type ParsedLine = { name: string };

function parsedName(line: string): ParsedLine | null {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith("#")) return null;
  const body = trimmed.startsWith("export ") ? trimmed.slice(7).trim() : trimmed;
  const mark = body.indexOf("=");
  if (mark <= 0) return null;
  const name = body.slice(0, mark).trim();
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) return null;
  return { name };
}

export function readEnvValues(text: string, keys: readonly string[]): Record<string, string> {
  const wanted = new Set(keys);
  const found: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const parsed = parsedName(line);
    if (!parsed || !wanted.has(parsed.name)) continue;
    const body = line.trim().startsWith("export ") ? line.trim().slice(7).trim() : line.trim();
    let value = body.slice(body.indexOf("=") + 1).trim();
    if ((value.startsWith("\"") && value.endsWith("\"")) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    found[parsed.name] = value;
  }
  return found;
}

export function applyEnv(text: string, updates: Record<string, string>): string {
  const seen = new Set<string>();
  const lines = text.split("\n");
  const next = lines.map((line) => {
    const parsed = parsedName(line);
    if (!parsed || !Object.prototype.hasOwnProperty.call(updates, parsed.name)) return line;
    seen.add(parsed.name);
    const trimmed = line.trimStart();
    const prefix = trimmed.startsWith("export ") ? "export " : "";
    return `${prefix}${parsed.name}=${updates[parsed.name]}`;
  });
  for (const [name, value] of Object.entries(updates)) {
    if (seen.has(name)) continue;
    if (next.length > 0 && next[next.length - 1] !== "") next.push("");
    next.push(`${name}=${value}`);
  }
  const body = next.join("\n");
  return body.endsWith("\n") || body.length === 0 ? body : `${body}\n`;
}
