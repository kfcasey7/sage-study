import { useState } from "react";
import { CheckCircle2, ExternalLink, KeyRound, Trash2 } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, Settings as SettingsT } from "../lib/types";
import { ErrorBanner, InfoBanner, Loading } from "../components/common";

const EFFORT_HELP: Record<string, string> = {
  low: "Fastest and cheapest. Fine for quick review sessions.",
  medium: "Recommended. Careful questions and grading at a moderate cost.",
  high: "Most thorough reasoning. Slower, and uses more tokens.",
};

export default function Settings() {
  const { settings, setSettings, toast, toggleTheme, theme } = useApp();
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  if (!settings) return <Loading message="Loading settings…" rotate={false} />;
  const s = settings.settings;

  async function save(patch: Partial<SettingsT>) {
    try {
      setSettings(await api.updateSettings(patch));
    } catch (e) {
      setError(asApiError(e).toBody());
    }
  }

  async function saveKey() {
    setBusy("save"); setError(null); setWarning(null);
    try {
      const res = await api.setKey(key);
      setSettings(res);
      setKey("");
      if (res.warning) setWarning(res.warning);
      else toast("API key verified and saved to your system keychain.", "success");
    } catch (e) {
      setError(asApiError(e).toBody());
    } finally { setBusy(null); }
  }

  async function testKey() {
    setBusy("test"); setError(null);
    try {
      await api.testKey();
      toast("Your API key works.", "success");
    } catch (e) {
      setError(asApiError(e).toBody());
    } finally { setBusy(null); }
  }

  async function removeKey() {
    setBusy("remove"); setError(null);
    try {
      setSettings(await api.deleteKey());
      toast("API key removed from the keychain.");
    } catch (e) {
      setError(asApiError(e).toBody());
    } finally { setBusy(null); }
  }

  const k = settings.key;
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Your API key, model, and how feedback is shown.</p>
        </div>
      </div>

      <ErrorBanner error={error} compact />
      {warning && <InfoBanner tone="warn">{warning}</InfoBanner>}

      <section className="card">
        <div className="card-title"><h2><KeyRound size={18} style={{ verticalAlign: -3, marginRight: 8 }} />Anthropic API key</h2>
          {k.key_set ? <span className="badge correct"><CheckCircle2 size={13} /> Set</span> : <span className="badge warn">Not set</span>}
        </div>
        <p className="muted">
          {k.key_set
            ? k.source === "keyring"
              ? <>A key ending in <code>…{k.last4}</code> is stored in your operating system's credential store.</>
              : <>Using the <code>ANTHROPIC_API_KEY</code> environment variable (key ending in <code>…{k.last4}</code>). A key saved here takes priority.</>
            : <>Sage Study needs an API key to write questions, grade answers, and build study guides. The key is kept in your OS credential store and never sent to the app's interface.</>}
        </p>
        <div className="row" style={{ alignItems: "stretch" }}>
          <input
            className="input mono"
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder={k.key_set ? "Paste a new key to replace it" : "sk-ant-…"}
            value={key}
            onChange={(e) => setKey(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && key.trim()) void saveKey(); }}
            style={{ flex: 1, minWidth: 260 }}
            aria-label="Anthropic API key"
          />
          <button className="btn primary" disabled={!key.trim() || !!busy} onClick={saveKey}>
            {busy === "save" ? <span className="spinner" /> : null} Save &amp; verify
          </button>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          {k.key_set && <button className="btn sm" onClick={testKey} disabled={!!busy}>{busy === "test" && <span className="spinner" />} Test key</button>}
          {k.key_set && k.source === "keyring" && <button className="btn sm ghost danger" onClick={removeKey} disabled={!!busy}><Trash2 size={14} /> Remove</button>}
          <span className="spacer" />
          <a className="small" href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">
            Get an API key <ExternalLink size={12} style={{ verticalAlign: -1 }} />
          </a>
        </div>
      </section>

      <section className="card">
        <h2>Model</h2>
        <p className="muted small">New sessions use these settings. Sessions in progress keep the model they started with, so their prompt cache stays valid.</p>
        <div className="stack">
          {settings.options.models.map((m) => {
            const price = settings.options.pricing[m.id];
            return (
              <label key={m.id} className={`option ${s.model === m.id ? "selected" : ""}`}>
                <input type="radio" name="model" checked={s.model === m.id} onChange={() => save({ model: m.id })} />
                <span className="opt-text">
                  <strong>{m.label}</strong> <code className="small">{m.id}</code>
                  <div className="muted small">{m.description}{price ? ` · $${price.input}/$${price.output} per million input/output tokens` : ""}</div>
                </span>
              </label>
            );
          })}
        </div>
        <hr className="divider" />
        <div className="stack">
          <div>
            <div style={{ fontWeight: 600, marginBottom: 8 }}>Thinking effort</div>
            <div className="segmented" role="radiogroup">
              {settings.options.efforts.map((e) => (
                <button key={e} className={s.effort === e ? "on" : ""} onClick={() => save({ effort: e as SettingsT["effort"] })} role="radio" aria-checked={s.effort === e}>
                  {e[0].toUpperCase() + e.slice(1)}
                </button>
              ))}
            </div>
            <div className="muted small" style={{ marginTop: 6 }}>{EFFORT_HELP[s.effort]}</div>
          </div>
          <label className="switch">
            <input type="checkbox" checked={s.fallback_enabled} onChange={(e) => save({ fallback_enabled: e.target.checked })} />
            <span className="track" />
            <span>
              Automatic fallback if a request is declined
              <div className="muted small" style={{ fontWeight: 400 }}>If Claude's safety filters decline a request (for example, chemistry or security course material), the API retries it on another model in the same call. Sonnet and Opus only.</div>
            </span>
          </label>
        </div>
      </section>

      <section className="card">
        <h2>Quiz &amp; appearance</h2>
        <div className="stack">
          <div>
            <div style={{ fontWeight: 600, marginBottom: 8 }}>Show feedback</div>
            <div className="segmented">
              <button className={s.feedback_mode === "immediate" ? "on" : ""} onClick={() => save({ feedback_mode: "immediate" })}>After each answer</button>
              <button className={s.feedback_mode === "end" ? "on" : ""} onClick={() => save({ feedback_mode: "end" })}>At the end</button>
            </div>
          </div>
          <div>
            <div style={{ fontWeight: 600, marginBottom: 8 }}>Theme</div>
            <div className="segmented">
              <button className={theme === "light" ? "on" : ""} onClick={() => theme !== "light" && toggleTheme()}>Light</button>
              <button className={theme === "dark" ? "on" : ""} onClick={() => theme !== "dark" && toggleTheme()}>Dark</button>
            </div>
          </div>
        </div>
      </section>

      <p className="muted small" style={{ marginTop: 20 }}>
        {settings.app.name} {settings.app.version} · Data is stored locally in <code>{settings.app.data_dir}</code>
      </p>
    </div>
  );
}
