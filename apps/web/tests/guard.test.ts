import assert from "node:assert/strict";
import test from "node:test";
import { jsonContent, safeToMutate, trustedOrigin } from "@/lib/guard";

test("only this portal's own loopback origin may change settings", () => {
  assert.equal(trustedOrigin(null, "127.0.0.1:3000"), true);
  assert.equal(trustedOrigin("http://127.0.0.1:3000", "127.0.0.1:3000"), true);
  assert.equal(trustedOrigin("http://localhost:3000", "localhost:3000"), true);
  assert.equal(trustedOrigin("http://evil.example", "127.0.0.1:3000"), false);
  assert.equal(trustedOrigin("null", "127.0.0.1:3000"), false);
  assert.equal(trustedOrigin("http://127.0.0.1:9999", "127.0.0.1:3000"), false);
  assert.equal(trustedOrigin("http://evil.example:3000", "evil.example:3000"), false);
});

test("a cross-site simple request (text/plain, foreign origin) is refused; the page's own JSON post passes", () => {
  const attack = new Headers({ host: "127.0.0.1:3000", origin: "http://evil.example", "content-type": "text/plain" });
  assert.equal(safeToMutate(attack), false);
  const noPreflightJsonFromEvil = new Headers({ host: "127.0.0.1:3000", origin: "http://evil.example", "content-type": "application/json" });
  assert.equal(safeToMutate(noPreflightJsonFromEvil), false);
  const own = new Headers({ host: "127.0.0.1:3000", origin: "http://127.0.0.1:3000", "content-type": "application/json; charset=utf-8" });
  assert.equal(safeToMutate(own), true);
  assert.equal(safeToMutate(new Headers({ host: "127.0.0.1:3000", "content-type": "text/plain" })), false);
  assert.equal(jsonContent("Application/JSON"), true);
});

test("only the settings the worker reads are writable", async () => {
  const { SETTINGS, isEditableKey } = await import("@/lib/settings");
  assert.deepEqual(SETTINGS.filter((field) => field.editable).map((field) => field.key).sort(), ["AWS_BEDROCK_API_KEY", "JEV_TYPESAFE_API_KEY"]);
  assert.equal(isEditableKey("AWS_BEDROCK_LLM"), false);
  assert.equal(isEditableKey("AWS_BEDROCK_API_KEY"), true);
  assert.equal(isEditableKey("PATH"), false);
});
