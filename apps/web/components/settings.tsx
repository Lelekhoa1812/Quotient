"use client";

/**
 * Motivation vs Logic
 * Motivation: Keys and model names are local options. A saved key must not be
 * sent back into the page.
 * Logic: GET reports presence and non-secret values. POST sends a secret only
 * when the field is filled. Blank secrets keep the saved value.
 */
import { useEffect, useState, useSyncExternalStore, type FormEvent } from "react";
import { Check, Copy } from "lucide-react";
import { copyToClipboard } from "@/lib/clipboard";
import { mcp } from "@/lib/mcp/client";
import {
  effectiveProvider,
  knownOverrides,
  loadPreference,
  nimChoice,
  providerLabel,
  providerModels,
  savePreference,
  speedLabel,
  type ModelOptions,
  type ModelPair,
  type ModelPreference,
} from "@/lib/models";
import { apiBase } from "@/lib/origin";
import type { SettingField } from "@/lib/settings";
import type { ModelProvider } from "@/lib/types";

type LoadedField = SettingField & { set: boolean; value: string };

const PROVIDER_ORDER: ModelProvider[] = ["bedrock", "nim"];

const ROLE_LABEL: Record<keyof ModelPair, string> = {
  slm: "Fast passes (easy tasks)",
  llm: "Long reasoning (complex tasks)",
};

/**
 * Motivation vs Logic
 * Motivation: The person chooses which model family runs the text analysis, and which NIM models run the
 * fast and the long-reasoning passes. The choice is kept on this computer and applies to meetings started
 * after it is made.
 * Logic: The server says which families it has set up (model_options). NIM is disabled, with a plain reason,
 * when it is not. Each change is saved at once. Radio buttons give the keyboard and screen-reader behaviour.
 */
function ModelChoice() {
  const [options, setOptions] = useState<ModelOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [preference, setPreference] = useState<ModelPreference | null>(null);
  const [note, setNote] = useState("");

  useEffect(() => {
    let cancel = false;
    // Read the saved choice here, not during render, so the page renders the same on the server and in the browser.
    setPreference(loadPreference());
    void (async () => {
      try {
        const loaded = await mcp.modelOptions();
        if (cancel) return;
        setOptions(loaded);
        setFailed(loaded === null);
      } catch {
        if (!cancel) setFailed(true);
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => {
      cancel = true;
    };
  }, []);

  function saveChoice(next: ModelPreference) {
    const saved = savePreference(next);
    setPreference(next);
    setNote(saved ? "Saved. New meetings use this choice. Meetings already started keep the model they were started with." : "This choice lasts for this visit only, because the browser would not keep it.");
  }

  if (loading) {
    return (
      <fieldset className="q-settings-group">
        <legend>Models</legend>
        <p className="q-muted">Loading the model choices.</p>
      </fieldset>
    );
  }
  if (!options) {
    return (
      <fieldset className="q-settings-group">
        <legend>Models</legend>
        <p role="alert">The model choices could not be loaded from this server. Meetings use the server's default model family.</p>
      </fieldset>
    );
  }

  const provider = effectiveProvider(preference, options) ?? options.default;
  const nimReady = options.providers.some((item) => item.id === "nim" && item.available);
  const bedrock = providerModels(options, "bedrock");

  return (
    <fieldset className="q-settings-group">
      <legend>Models</legend>
      <div className="q-segmented" role="group" aria-label="Model family">
        {PROVIDER_ORDER.map((id) => {
          const available = id === "nim" ? nimReady : options.providers.some((item) => item.id === id && item.available);
          return (
            <label key={id}>
              <input
                className="q-sr"
                type="radio"
                name="model-provider"
                value={id}
                checked={provider === id}
                disabled={!available}
                aria-describedby={!available && id === "nim" ? "nim-unavailable" : undefined}
                onChange={() => saveChoice({ provider: id, overrides: preference?.overrides ?? {} })}
              />
              <span>{providerLabel(id)}</span>
            </label>
          );
        })}
      </div>
      {!nimReady ? <p id="nim-unavailable" className="q-muted">NVIDIA NIM isn't set up on this server.</p> : null}
      {provider === "bedrock" ? (
        <dl className="q-model-pins">
          <dt>Fast passes</dt>
          <dd>{bedrock.slm || "Not set"}</dd>
          <dt>Long reasoning</dt>
          <dd>{bedrock.llm || "Not set"}</dd>
        </dl>
      ) : null}
      {provider === "nim" ? (
        options.nimModels.length === 0 ? (
          <p className="q-muted">No NVIDIA models are listed by this server.</p>
        ) : (
          (["slm", "llm"] as const).map((role) => {
            const current = nimChoice(preference, options, role);
            const model = options.nimModels.find((item) => item.id === current);
            const id = `model-${role}`;
            return (
              <div key={role} className="q-label">
                <label htmlFor={id}>{ROLE_LABEL[role]}</label>
                <select
                  id={id}
                  className="q-field"
                  value={current}
                  aria-describedby={`${id}-help`}
                  onChange={(event) => saveChoice({ provider: "nim", overrides: knownOverrides({ ...(preference?.overrides ?? {}), [role]: event.target.value }, options) })}
                >
                  {options.nimModels.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}{item.speed ? ` (${speedLabel(item.speed)})` : ""}
                    </option>
                  ))}
                </select>
                <div id={`${id}-help`} className="q-muted">
                  {model?.speed ? <span className="q-badge" data-speed={model.speed}>{speedLabel(model.speed)}</span> : null}
                  {model?.notes ? <span> {model.notes}</span> : null}
                  {options.roles[role] ? <span className="q-faint"> {options.roles[role]}</span> : null}
                </div>
              </div>
            );
          })
        )
      ) : null}
      <p className="q-muted">Audio transcription and video scanning always use AWS Bedrock. This choice applies to the text analysis, and to everything for a transcript upload.</p>
      {note ? <p role="status">{note}</p> : null}
    </fieldset>
  );
}



type ApiKeyRecord = {
  key_id: string;
  token?: string;
  created_at?: string | null;
  revoked_at?: string | null;
};

/**
 * Motivation vs Logic
 * Motivation: The integration key has to be readable again, copied, and revoked.
 * Logic: GET returns the active token. Show toggles the field. Copy writes it.
 * Revoke and Generate are separate posts. A blank token means there is nothing to reveal.
 */
function IntegrationKey() {
  const [record, setRecord] = useState<ApiKeyRecord | null>(null);
  const [scope, setScope] = useState<"local" | "shared" | "">("");
  const [visible, setVisible] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancel = false;
    void (async () => {
      try {
        const response = await fetch("/api/keys", { cache: "no-store" });
        const body = await response.json() as { key?: ApiKeyRecord | null; scope?: "local" | "shared"; error?: string };
        if (cancel) return;
        if (!response.ok) {
          setError(body.error || "The API key could not be loaded.");
          return;
        }
        setRecord(body.key ?? null);
        setScope(body.scope === "shared" ? "shared" : "local");
      } catch {
        if (!cancel) setError("The API key could not be loaded.");
      } finally {
        if (!cancel) setLoaded(true);
      }
    })();
    return () => {
      cancel = true;
    };
  }, []);

  async function send(action: "issue" | "revoke") {
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const response = await fetch("/api/keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const body = await response.json() as { key?: ApiKeyRecord | null; scope?: "local" | "shared"; error?: string };
      if (!response.ok) {
        setError(body.error || "The API key could not be changed.");
        return;
      }
      setRecord(body.key ?? null);
      if (body.scope === "shared" || body.scope === "local") setScope(body.scope);
      setVisible(action === "issue");
      setMessage(action === "issue" ? "API key generated." : "API key revoked.");
    } catch {
      setError("The API key could not be changed.");
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!record?.token) return;
    const ok = await copyToClipboard(record.token);
    if (ok) {
      setCopied(true);
      setMessage("Copied API key.");
      setError("");
      window.setTimeout(() => {
        setCopied(false);
      }, 2000);
    } else {
      setMessage("");
      setError("The API key could not be copied.");
    }
  }

  const active = Boolean(record && !record.revoked_at && record.token);
  const scopeNote = scope === "shared"
    ? "This key is accepted by this computer and by the deployed load balancer. It does not expire."
    : "This key is stored on this computer only. The deployed load balancer will not accept it. It does not expire.";

  return (
    <fieldset className="q-settings-group">
      <legend id="integration-key-heading">Integration</legend>
      {scope ? <p className="q-muted">{scopeNote}</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {message ? <p role="status">{message}</p> : null}
      {!loaded && !error ? <p className="q-muted">Loading the API key.</p> : null}
      {loaded && !active ? (
        <div className="q-start-actions">
          <button className="q-btn" type="button" disabled={busy} onClick={() => void send("issue")}>
            {busy ? "Generating" : "Generate API key"}
          </button>
        </div>
      ) : null}
      {active && record?.token ? (
        <div className="q-label">
          <span>API key</span>
          <input
            className="q-field"
            type={visible ? "text" : "password"}
            readOnly
            value={record.token}
            aria-label="API key"
            spellCheck={false}
            autoComplete="off"
          />
          <div className="q-start-actions">
            <button className="q-btn-ghost" type="button" aria-pressed={visible} onClick={() => setVisible((current) => !current)}>
              {visible ? "Hide" : "Show"}
            </button>
            <button
              className="q-btn-ghost inline-flex items-center gap-1.5"
              type="button"
              aria-label={copied ? "Copied API key" : "Copy API key"}
              onClick={() => void copy()}
            >
              {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
              <span>{copied ? "Copied" : "Copy"}</span>
            </button>
            <button className="q-btn-ghost" type="button" disabled={busy} onClick={() => void send("revoke")}>
              {busy ? "Revoking" : "Revoke"}
            </button>
          </div>
        </div>
      ) : null}
    </fieldset>
  );
}

export function Settings() {
  const [fields, setFields] = useState<LoadedField[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [blocked, setBlocked] = useState(false);
  const [shared, setShared] = useState(false);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const base = useSyncExternalStore(
    () => () => undefined,
    () => apiBase({ hostname: window.location.hostname, origin: window.location.origin }),
    () => apiBase(null),
  );

  useEffect(() => {
    let cancel = false;
    void (async () => {
      try {
        const response = await fetch("/api/settings", { cache: "no-store" });
        const body = await response.json() as { local?: boolean; deployment?: boolean; error?: string; fields?: LoadedField[] };
        if (cancel) return;
        if (response.status === 403 || body.local === false) {
          setBlocked(true);
          return;
        }
        setShared(body.deployment === true);
        if (!response.ok) {
          setError(body.error || "Settings could not be loaded.");
          return;
        }
        const loaded = body.fields ?? [];
        setFields(loaded);
        setDraft(Object.fromEntries(loaded.map((field) => [field.key, field.secret ? "" : field.value])));
      } catch {
        if (!cancel) setError("Settings could not be loaded.");
      } finally {
        if (!cancel) setReady(true);
      }
    })();
    return () => {
      cancel = true;
    };
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    setError("");
    const values: Record<string, string> = {};
    for (const field of fields) {
      if (!field.editable) continue;
      const value = (draft[field.key] ?? "").trim();
      if (field.secret && !value) continue;
      values[field.key] = value;
    }
    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values }),
      });
      const body = await response.json() as { error?: string };
      if (!response.ok) {
        setError(body.error || "Settings could not be saved.");
        return;
      }
      setMessage("Saved. The new values apply the next time Quotient starts.");
      setFields((current) => current.map((field) => {
        const value = (draft[field.key] ?? "").trim();
        if (field.secret) return value ? { ...field, set: true } : field;
        return { ...field, value, set: value.length > 0 };
      }));
      setDraft((current) => {
        const next = { ...current };
        for (const field of fields) if (field.secret) next[field.key] = "";
        return next;
      });
    } catch {
      setError("Settings could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  const groups = ["Keys", "Models"] as const;

  return (
    <main id="main" tabIndex={-1} className="q-portal">
      <header className="q-page-head">
        <h1>Settings</h1>
        <p className="q-lede">{!ready
          ? "Loading settings."
          : shared
            ? "Choose the model family for text analysis under Models. The integration key can be shown, copied, and revoked. Service keys are the task role on this deployment. Release pins are shown for reference."
            : "Choose the model family for text analysis under Models. API keys for this computer: a blank service key keeps the one already saved. The integration key can be shown, copied, and revoked. Release pins are shown for reference."}</p>
      </header>
      {ready && !blocked ? <p className="q-muted">API base {base}</p> : null}
      {blocked ? <p role="status">Settings can be changed on this computer only.</p> : null}
      <ModelChoice />
      {!blocked ? <IntegrationKey /> : null}
      {error ? <p role="alert">{error}</p> : null}
      {!blocked && fields.length === 0 && !error ? <p className="q-muted">Loading settings.</p> : null}
      {!blocked && fields.length > 0 ? (
        <form className="q-settings" onSubmit={(event) => void onSubmit(event)}>
          {groups.map((group) => {
            const grouped = fields.filter((field) => field.group === group);
            if (grouped.length === 0) return null;
            return (
            <fieldset key={group} className="q-settings-group">
              <legend>{group === "Models" ? "Release pins" : group}</legend>
              {grouped.map((field) => (
                <label key={field.key} className="q-label">
                  {field.label}
                  <input
                    className="q-field"
                    type={field.secret ? "password" : "text"}
                    name={field.key}
                    autoComplete="off"
                    spellCheck={false}
                    value={draft[field.key] ?? ""}
                    readOnly={!field.editable}
                    aria-readonly={!field.editable}
                    placeholder={field.secret && field.set ? "Leave blank to keep it" : ""}
                    onChange={(event) => setDraft((current) => ({ ...current, [field.key]: event.target.value }))}
                  />
                  {field.secret && field.set ? <span className="q-muted">A key is already saved.</span> : null}
                </label>
              ))}
            </fieldset>
            );
          })}
          {fields.some((field) => field.editable) ? (
          <div className="q-start-actions">
            <button className="q-btn" type="submit" disabled={busy}>
              {busy ? "Saving" : "Save"}
            </button>
          </div>
          ) : null}
          {message ? <p role="status">{message}</p> : null}
        </form>
      ) : null}
    </main>
  );
}
