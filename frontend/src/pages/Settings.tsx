import { useState } from "react";
import { CheckCircle2, RefreshCw, Terminal, XCircle } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, Settings as SettingsT } from "../lib/types";
import { ErrorBanner, Loading } from "../components/common";
import { YoutubeKeyCard } from "../components/YoutubeKeyCard";

function StatusRow({ ok, label, detail }: { ok: boolean; label: string; detail?: string | null }) {
  return (
    <div className="row" style={{ gap: 10, padding: "6px 0" }}>
      {ok ? <CheckCircle2 size={18} color="var(--correct)" /> : <XCircle size={18} color="var(--incorrect)" />}
      <span style={{ fontWeight: 600 }}>{label}</span>
      {detail && <span className="muted small">{detail}</span>}
    </div>
  );
}

export default function Settings() {
  const { settings, setSettings, cli, refreshCli, toggleTheme, theme } = useApp();
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const [checking, setChecking] = useState(false);

  if (!settings) return <Loading message="Loading settings…" rotate={false} />;
  const s = settings.settings;
  const models = settings.options.models;

  async function save(patch: Partial<SettingsT>) {
    try {
      setSettings(await api.updateSettings(patch));
    } catch (e) {
      setError(asApiError(e).toBody());
    }
  }

  async function recheck() {
    setChecking(true);
    await refreshCli(true);
    setChecking(false);
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Claude Code connection, models, and how feedback is shown.</p>
        </div>
      </div>

      <ErrorBanner error={error} compact />

      <section className="card">
        <div className="card-title">
          <h2><Terminal size={18} style={{ verticalAlign: -3, marginRight: 8 }} />Claude Code status</h2>
          {cli == null ? <span className="badge">Checking…</span>
            : cli.ready ? <span className="badge correct"><CheckCircle2 size={13} /> Ready</span>
            : <span className="badge incorrect">Needs attention</span>}
        </div>
        <p className="muted">
          Sage Study runs every AI request through the Claude Code CLI on this computer, using your Claude
          subscription login. No API key is used and nothing is billed to an API account.
        </p>
        {cli && (
          <div>
            <StatusRow ok={cli.installed} label={cli.installed ? "Claude Code found" : "Claude Code not found"} detail={cli.version ?? cli.path} />
            <StatusRow ok={cli.logged_in} label={cli.logged_in ? "Logged in" : "Not logged in"}
              detail={cli.logged_in ? [cli.subscription && `${cli.subscription[0].toUpperCase()}${cli.subscription.slice(1)} plan`, cli.auth_method && `via ${cli.auth_method}`].filter(Boolean).join(" · ") : null} />
          </div>
        )}
        {cli?.message && (
          <div className={`banner ${cli.ready ? "info" : "warn"}`} style={{ marginTop: 12, marginBottom: 0 }}>
            <Terminal size={20} />
            <div className="banner-body">
              <div>{cli.message}</div>
              {!cli.ready && (
                <ol className="small" style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                  {!cli.installed && <li>Install Claude Code: <a href="https://claude.com/claude-code" target="_blank" rel="noreferrer">claude.com/claude-code</a></li>}
                  <li>Open a terminal and run <code>claude</code></li>
                  <li>Log in with your Claude Pro account (type <code>/login</code> if it doesn't prompt you), then click Check again.</li>
                </ol>
              )}
            </div>
          </div>
        )}
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn sm" onClick={recheck} disabled={checking}>{checking ? <span className="spinner" /> : <RefreshCw size={14} />} Check again</button>
        </div>
      </section>

      <section className="card">
        <h2>Models</h2>
        <p className="muted small">
          New sessions use these choices; a session in progress keeps the models it started with. Lighter models
          respond faster and use less of your plan's usage limit.
        </p>
        <div className="grid-2">
          <label className="field">
            Mapping topics &amp; writing questions
            <select className="select" value={s.model_fast} onChange={(e) => save({ model_fast: e.target.value })}>
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}{m.id === "haiku" ? " (default)" : ""}</option>)}
            </select>
            <span className="field-hint">{models.find((m) => m.id === s.model_fast)?.description}</span>
          </label>
          <label className="field">
            Grading written, math &amp; code answers, and study guides
            <select className="select" value={s.model_smart} onChange={(e) => save({ model_smart: e.target.value })}>
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}{m.id === "sonnet" ? " (default)" : ""}</option>)}
            </select>
            <span className="field-hint">{models.find((m) => m.id === s.model_smart)?.description}</span>
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

      <YoutubeKeyCard />

      <p className="muted small" style={{ marginTop: 20 }}>
        {settings.app.name} {settings.app.version} · Data is stored locally in <code>{settings.app.data_dir}</code>
      </p>
    </div>
  );
}
