import assert from "node:assert/strict";
import test from "node:test";
import {
  MODELS_STORAGE_KEY,
  effectiveProvider,
  knownOverrides,
  loadPreference,
  nimChoice,
  normalisePreference,
  parseModelOptions,
  parsePreference,
  providerModels,
  savePreference,
  speedLabel,
  submitModelArgs,
  type ModelOptions,
} from "@/lib/models";

const SERVER = {
  default: "bedrock",
  providers: [
    { id: "bedrock", label: "AWS Bedrock", available: true, models: { slm: "bedrock-small", llm: "bedrock-large" } },
    { id: "nim", label: "NVIDIA NIM", available: true, models: { slm: "nim-fast", llm: "nim-deep" } },
  ],
  nim_models: [
    { id: "nim-fast", label: "Fast model", context: 128000, max_output: "8K", speed: "fast", notes: "Quick checks." },
    { id: "nim-deep", label: "Deep model", context: "256K", max_output: 16384, speed: "slow", notes: "Slower reasoning." },
    { id: "nim-odd", label: "", context: null, speed: "sideways", notes: 4 },
    { label: "No id" },
  ],
  roles: { slm: "Fast passes for easy tasks.", llm: "Long reasoning for complex tasks." },
};

function options(overrides: Partial<ModelOptions> = {}): ModelOptions {
  const parsed = parseModelOptions({ structuredContent: SERVER });
  assert.ok(parsed, "the sample server answer must parse");
  return { ...parsed, ...overrides };
}

test("model_options reads providers, NIM models and role text, and drops what it cannot use", () => {
  const parsed = options();
  assert.equal(parsed.default, "bedrock");
  assert.deepEqual(parsed.providers.map((item) => [item.id, item.available]), [["bedrock", true], ["nim", true]]);
  assert.deepEqual(providerModels(parsed, "nim"), { slm: "nim-fast", llm: "nim-deep" });
  // Entries without an id are dropped; a missing label falls back to the id; odd speed and notes become safe values.
  assert.deepEqual(parsed.nimModels.map((model) => model.id), ["nim-fast", "nim-deep", "nim-odd"]);
  assert.equal(parsed.nimModels[0].context, "128000");
  assert.equal(parsed.nimModels[1].maxOutput, "16384");
  assert.equal(parsed.nimModels[2].label, "nim-odd");
  assert.equal(parsed.nimModels[2].speed, null);
  assert.equal(parsed.nimModels[2].notes, "");
  assert.equal(parsed.roles.slm, "Fast passes for easy tasks.");
});

test("model_options with no usable provider, or a plain error, reads as unknown", () => {
  assert.equal(parseModelOptions({ providers: [] }), null);
  assert.equal(parseModelOptions({ providers: [{ id: "openai", available: true }] }), null);
  assert.equal(parseModelOptions({ error: "down" }), null);
  assert.equal(parseModelOptions(null), null);
  const withoutDefault = parseModelOptions({ providers: SERVER.providers });
  assert.equal(withoutDefault?.default, "bedrock");
});

test("a saved preference is read only when its provider is known", () => {
  assert.equal(normalisePreference({ provider: "azure" }), null);
  assert.equal(normalisePreference(null), null);
  assert.equal(normalisePreference("nim"), null);
  assert.deepEqual(normalisePreference({ provider: "nim", overrides: { slm: "nim-fast", llm: 7 } }), {
    provider: "nim",
    overrides: { slm: "nim-fast" },
  });
  // Overrides survive a switch to Bedrock, so switching back restores the picks.
  assert.deepEqual(normalisePreference({ provider: "bedrock", overrides: { llm: "nim-deep" } }), {
    provider: "bedrock",
    overrides: { llm: "nim-deep" },
  });
});

test("stored text that is not the saved shape counts as nothing saved", () => {
  assert.equal(parsePreference(null), null);
  assert.equal(parsePreference(""), null);
  assert.equal(parsePreference("{not json"), null);
  assert.equal(parsePreference("[]"), null);
  assert.deepEqual(parsePreference(JSON.stringify({ provider: "nim", overrides: {} })), { provider: "nim", overrides: {} });
});

test("overrides keep only the NIM model ids the server offers", () => {
  const parsed = options();
  assert.deepEqual(knownOverrides({ slm: "nim-fast", llm: "made-up" }, parsed), { slm: "nim-fast" });
  assert.deepEqual(knownOverrides({ slm: "nim-odd" }, parsed), { slm: "nim-odd" });
  assert.deepEqual(knownOverrides({}, parsed), {});
});

test("a NIM role shows the person's pick, or the provider default when the pick is no longer offered", () => {
  const parsed = options();
  assert.equal(nimChoice(null, parsed, "slm"), "nim-fast");
  assert.equal(nimChoice({ provider: "nim", overrides: { llm: "nim-deep" } }, parsed, "llm"), "nim-deep");
  assert.equal(nimChoice({ provider: "nim", overrides: { llm: "retired" } }, parsed, "llm"), "nim-deep");
});

test("with nothing saved, the server default family is used", () => {
  const parsed = options();
  assert.equal(effectiveProvider(null, parsed), "bedrock");
  assert.deepEqual(submitModelArgs(null, parsed), { model_provider: "bedrock" });
  const nimDefault = options({ default: "nim" });
  assert.equal(effectiveProvider(null, nimDefault), "nim");
  assert.deepEqual(submitModelArgs(null, nimDefault), { model_provider: "nim" });
});

test("with no server answer and nothing saved, nothing is sent and the server decides", () => {
  assert.equal(submitModelArgs(null, null), null);
  assert.deepEqual(submitModelArgs({ provider: "nim", overrides: { slm: "nim-fast" } }, null), {
    model_provider: "nim",
    model_overrides: { slm: "nim-fast" },
  });
});

test("a saved NIM choice is sent with its overrides; unknown ids are not", () => {
  const parsed = options();
  assert.deepEqual(
    submitModelArgs({ provider: "nim", overrides: { slm: "nim-fast", llm: "made-up" } }, parsed),
    { model_provider: "nim", model_overrides: { slm: "nim-fast" } },
  );
  assert.deepEqual(submitModelArgs({ provider: "nim", overrides: {} }, parsed), { model_provider: "nim" });
});

test("Bedrock is sent without overrides, even when NIM picks are kept", () => {
  assert.deepEqual(submitModelArgs({ provider: "bedrock", overrides: { slm: "nim-fast" } }, options()), { model_provider: "bedrock" });
});

test("a saved NIM choice falls back to the server default when NIM is not set up", () => {
  const parsed = options({
    providers: [
      { id: "bedrock", label: "AWS Bedrock", available: true, models: { slm: "bedrock-small", llm: "bedrock-large" } },
      { id: "nim", label: "NVIDIA NIM", available: false, models: { slm: "", llm: "" } },
    ],
  });
  assert.equal(effectiveProvider({ provider: "nim", overrides: { slm: "nim-fast" } }, parsed), "bedrock");
  assert.deepEqual(submitModelArgs({ provider: "nim", overrides: { slm: "nim-fast" } }, parsed), { model_provider: "bedrock" });
});

test("storage round trip, and a blocked store leaves the page working", () => {
  const cells = new Map<string, string>();
  const store = {
    getItem: (key: string) => cells.get(key) ?? null,
    setItem: (key: string, value: string) => void cells.set(key, value),
  };
  assert.equal(savePreference({ provider: "nim", overrides: { llm: "nim-deep" } }, store), true);
  assert.equal(cells.get(MODELS_STORAGE_KEY), JSON.stringify({ provider: "nim", overrides: { llm: "nim-deep" } }));
  assert.deepEqual(loadPreference(store), { provider: "nim", overrides: { llm: "nim-deep" } });

  const refusing = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("quota");
    },
  };
  assert.equal(loadPreference(refusing), null);
  assert.equal(savePreference({ provider: "bedrock", overrides: {} }, refusing), false);
  assert.equal(loadPreference(null), null);
  assert.equal(savePreference({ provider: "bedrock", overrides: {} }, null), false);
});

test("speed badges read Fast and Slow", () => {
  assert.equal(speedLabel("fast"), "Fast");
  assert.equal(speedLabel("slow"), "Slow");
});
