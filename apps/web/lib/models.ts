/**
 * Motivation vs Logic
 * Motivation: The person chooses which model family runs the text analysis. The choice has to survive
 * a reload, must never name a model the server does not offer, and is fixed for each meeting when it
 * is started; a running meeting keeps what it was started with.
 * Logic: Parse the model_options result and the saved preference defensively. Normalising drops an
 * unknown provider and unknown model ids. Storage access is wrapped, so a blocked store leaves the
 * page working on the server's default. effectiveProvider and submitModelArgs turn the choice into
 * the submit_meeting arguments, falling back to the server default when the chosen family is not set up.
 */

import { unwrapTool } from "@/lib/graph";
import { asArray, asFinite, asRecord, asString } from "@/lib/json";
import type { ModelProvider } from "@/lib/types";

export const MODELS_STORAGE_KEY = "quotient.models.v1";

export type ModelPair = { slm: string; llm: string };

export type NimModel = {
  id: string;
  label: string;
  /** Context window as the server wrote it, for example "128K", or "" when unknown. */
  context: string;
  maxOutput: string;
  speed: "fast" | "slow" | null;
  notes: string;
};

export type ProviderOption = {
  id: ModelProvider;
  label: string;
  available: boolean;
  models: ModelPair;
};

export type ModelOptions = {
  default: ModelProvider;
  providers: ProviderOption[];
  nimModels: NimModel[];
  /** What each role is for, as helper text. */
  roles: ModelPair;
};

/** The saved choice. Overrides hold only the NIM model ids the person picked. */
export type ModelPreference = { provider: ModelProvider; overrides: Partial<ModelPair> };

/** The arguments added to submit_meeting. */
export type SubmitModelArgs = { model_provider: ModelProvider; model_overrides?: Partial<ModelPair> };

const PROVIDER_LABEL: Record<ModelProvider, string> = { bedrock: "AWS Bedrock", nim: "NVIDIA NIM" };

export function providerLabel(provider: ModelProvider): string {
  return PROVIDER_LABEL[provider];
}

/** The speed badge text for a NIM model. */
export function speedLabel(speed: "fast" | "slow"): string {
  return speed === "fast" ? "Fast" : "Slow";
}

function parseProvider(value: unknown): ModelProvider | null {
  return value === "bedrock" || value === "nim" ? value : null;
}

function parsePair(value: unknown): ModelPair {
  const record = asRecord(value);
  return { slm: asString(record?.slm)?.trim() ?? "", llm: asString(record?.llm)?.trim() ?? "" };
}

/** A number or a string from the server, shown as text; anything else is empty. */
function text(value: unknown): string {
  if (typeof value === "string") return value.trim();
  const number = asFinite(value);
  return number === null ? "" : String(number);
}

function parseNimModel(value: unknown): NimModel | null {
  const record = asRecord(value);
  const id = asString(record?.id)?.trim();
  if (!record || !id) return null;
  const speed = record.speed === "fast" || record.speed === "slow" ? record.speed : null;
  return {
    id,
    label: asString(record.label)?.trim() || id,
    context: text(record.context),
    maxOutput: text(record.max_output),
    speed,
    notes: asString(record.notes)?.trim() ?? "",
  };
}

/** Read the model_options result. Null when it has no providers, so the page can say the choice is unavailable. */
export function parseModelOptions(result: unknown): ModelOptions | null {
  const body = asRecord(unwrapTool(result));
  if (!body) return null;
  const providers: ProviderOption[] = [];
  for (const entry of asArray(body.providers)) {
    const row = asRecord(entry);
    const id = parseProvider(row?.id);
    if (!row || !id) continue;
    providers.push({
      id,
      label: asString(row.label)?.trim() || providerLabel(id),
      available: row.available === true,
      models: parsePair(row.models),
    });
  }
  if (providers.length === 0) return null;
  return {
    default: parseProvider(body.default) ?? "bedrock",
    providers,
    nimModels: asArray(body.nim_models).map(parseNimModel).filter((model): model is NimModel => model !== null),
    roles: parsePair(body.roles),
  };
}

function parseOverrides(value: unknown): Partial<ModelPair> {
  const record = asRecord(value);
  const overrides: Partial<ModelPair> = {};
  for (const role of ["slm", "llm"] as const) {
    const id = asString(record?.[role])?.trim();
    if (id && id.length <= 200) overrides[role] = id;
  }
  return overrides;
}

/**
 * Read a saved preference. Unknown providers make it null; an override that is not a text id is dropped.
 * Known model ids are checked against the server later, by knownOverrides.
 */
export function normalisePreference(value: unknown): ModelPreference | null {
  const record = asRecord(value);
  const provider = parseProvider(record?.provider);
  if (!record || !provider) return null;
  // Overrides are kept even while Bedrock is chosen, so switching back to NIM restores the picks.
  return { provider, overrides: parseOverrides(record.overrides) };
}

/** Parse the stored text. Anything that is not the saved shape is treated as nothing saved. */
export function parsePreference(raw: string | null | undefined): ModelPreference | null {
  if (!raw) return null;
  try {
    return normalisePreference(JSON.parse(raw) as unknown);
  } catch {
    return null;
  }
}

/** Keep only the overrides that the server offers as NIM models. */
export function knownOverrides(overrides: Partial<ModelPair>, options: ModelOptions): Partial<ModelPair> {
  const known = new Set(options.nimModels.map((model) => model.id));
  const kept: Partial<ModelPair> = {};
  if (overrides.slm && known.has(overrides.slm)) kept.slm = overrides.slm;
  if (overrides.llm && known.has(overrides.llm)) kept.llm = overrides.llm;
  return kept;
}

/** The models a provider runs by default, as the server pins them. */
export function providerModels(options: ModelOptions, provider: ModelProvider): ModelPair {
  return options.providers.find((item) => item.id === provider)?.models ?? { slm: "", llm: "" };
}

/** The NIM model shown for a role: the person's pick when the server still offers it, else the provider default. */
export function nimChoice(preference: ModelPreference | null, options: ModelOptions, role: keyof ModelPair): string {
  const picked = knownOverrides(preference?.overrides ?? {}, options)[role];
  return picked ?? providerModels(options, "nim")[role];
}

function isAvailable(options: ModelOptions, provider: ModelProvider): boolean {
  return options.providers.some((item) => item.id === provider && item.available);
}

/**
 * The family a meeting will run on: the saved choice when the server has it set up, else the server default.
 * With no server answer, the saved choice is taken as it is; with neither, null (the server decides).
 */
export function effectiveProvider(preference: ModelPreference | null, options: ModelOptions | null): ModelProvider | null {
  if (!options) return preference?.provider ?? null;
  const wanted = preference?.provider ?? options.default;
  return isAvailable(options, wanted) ? wanted : options.default;
}

/**
 * The submit_meeting arguments for the current choice. Overrides go only with NIM, and only the ids the
 * server offers. Null when there is nothing to send, so the server applies its own default.
 */
export function submitModelArgs(preference: ModelPreference | null, options: ModelOptions | null): SubmitModelArgs | null {
  const provider = effectiveProvider(preference, options);
  if (!provider) return null;
  if (provider !== "nim" || preference?.provider !== "nim") return { model_provider: provider };
  const overrides = options ? knownOverrides(preference.overrides, options) : preference.overrides;
  return Object.keys(overrides).length > 0 ? { model_provider: provider, model_overrides: { ...overrides } } : { model_provider: provider };
}

type Store = Pick<Storage, "getItem" | "setItem">;

/** localStorage, or null when the browser refuses access (private windows, blocked site data). */
function browserStore(): Store | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function loadPreference(store: Store | null = browserStore()): ModelPreference | null {
  try {
    return parsePreference(store?.getItem(MODELS_STORAGE_KEY));
  } catch {
    return null;
  }
}

/** Save the choice. Returns false when the browser would not keep it; the page still works for this visit. */
export function savePreference(preference: ModelPreference, store: Store | null = browserStore()): boolean {
  try {
    if (!store) return false;
    store.setItem(MODELS_STORAGE_KEY, JSON.stringify(preference));
    return true;
  } catch {
    return false;
  }
}
