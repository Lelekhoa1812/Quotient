"use client";

/**
 * Motivation vs Logic
 * Motivation: Keys and model names are local options. A saved key must not be
 * sent back into the page.
 * Logic: GET reports presence and non-secret values. POST sends a secret only
 * when the field is filled. Blank secrets keep the saved value.
 */
import { useEffect, useState, type FormEvent } from "react";
import type { SettingField } from "@/lib/settings";

type LoadedField = SettingField & { set: boolean; value: string };

export function Settings() {
  const [fields, setFields] = useState<LoadedField[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [blocked, setBlocked] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancel = false;
    void (async () => {
      try {
        const response = await fetch("/api/settings", { cache: "no-store" });
        const body = await response.json() as { local?: boolean; error?: string; fields?: LoadedField[] };
        if (cancel) return;
        if (response.status === 403 || body.local === false) {
          setBlocked(true);
          return;
        }
        if (!response.ok) {
          setError(body.error || "Settings could not be loaded.");
          return;
        }
        const loaded = body.fields ?? [];
        setFields(loaded);
        setDraft(Object.fromEntries(loaded.map((field) => [field.key, field.secret ? "" : field.value])));
      } catch {
        if (!cancel) setError("Settings could not be loaded.");
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
    <main className="q-portal">
      <header className="q-page-head">
        <h1>Settings</h1>
        <p className="q-lede">API keys for this computer. A blank key keeps the one already saved. The models Quotient uses are set by its release and are shown for reference.</p>
      </header>
      {blocked ? <p role="status">Settings can be changed on this computer only.</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {!blocked && fields.length === 0 && !error ? <p className="q-muted">Loading settings.</p> : null}
      {!blocked && fields.length > 0 ? (
        <form className="q-settings" onSubmit={(event) => void onSubmit(event)}>
          {groups.map((group) => (
            <fieldset key={group} className="q-settings-group">
              <legend>{group === "Models" ? "Models in use (set by the release)" : group}</legend>
              {fields.filter((field) => field.group === group).map((field) => (
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
          ))}
          <div className="q-start-actions">
            <button className="q-btn" type="submit" disabled={busy}>
              {busy ? "Saving" : "Save"}
            </button>
          </div>
          {message ? <p role="status">{message}</p> : null}
        </form>
      ) : null}
    </main>
  );
}
