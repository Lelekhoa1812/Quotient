/**
 * Motivation vs Logic
 * Motivation: Settings and key admin have to follow the deployment, and a
 * value baked in at image build would ignore the task environment.
 * Logic: Read QUOTIENT_* through a dynamic key so the server bundle keeps the
 * runtime environment. Staging and production are the shared deployment.
 */

export function runtimeEnv(name: string): string {
  return String(process.env[name] ?? "").trim();
}

export function deployment(): boolean {
  const value = runtimeEnv("QUOTIENT_ENVIRONMENT").toLowerCase();
  return value === "staging" || value === "production";
}
