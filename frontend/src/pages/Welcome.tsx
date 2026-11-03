import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, ExternalLink, PlayCircle, RefreshCw, Terminal, XCircle } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody } from "../lib/types";
import { ErrorBanner, Loading } from "../components/common";
import { YoutubeKeyCard } from "../components/YoutubeKeyCard";

function Check({ ok, checking, title, children }: { ok: boolean; checking: boolean; title: string; children?: React.ReactNode }) {
  return (
    <div className="row" style={{ gap: 12, alignItems: "flex-start", padding: "10px 0" }}>
      <span style={{ flexShrink: 0, marginTop: 2 }}>
        {checking ? <span className="spinner" /> : ok ? <CheckCircle2 size={20} color="var(--correct)" /> : <XCircle size={20} color="var(--incorrect)" />}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600 }}>{title}</div>
        {!checking && !ok && <div className="muted small" style={{ marginTop: 4 }}>{children}</div>}
      </div>
    </div>
  );
}

/** First-run setup: a check or a plain-English fix for each requirement, then an optional demo. */
export default function Welcome() {
  const { settings, setSettings, cli, refreshCli, bumpHistory } = useApp();
  const navigate = useNavigate();
  const [checking, setChecking] = useState(false);
  const [loadingDemo, setLoadingDemo] = useState(false);
  const [error, setError] = useState<ApiErrorBody | null>(null);

  if (!settings) return <Loading message="Getting things ready…" rotate={false} />;
  const docsUrl = settings.app.install_docs_url;

  async function recheck() {
    setChecking(true);
    await refreshCli(true);
    setChecking(false);
  }

  async function finish(): Promise<boolean> {
    try {
      setSettings(await api.updateSettings({ setup_complete: true }));
      return true;
    } catch (e) {
      setError(asApiError(e).toBody());
      return false;
    }
  }

  async function tryDemo() {
    setLoadingDemo(true);
    setError(null);
    try {
      const demo = await api.loadDemo();
      bumpHistory();
      if (await finish()) navigate(`/sets/${demo.id}`);
    } catch (e) {
      setError(asApiError(e).toBody());
    } finally {
      setLoadingDemo(false);
    }
  }

  return (
    <div className="page" style={{ maxWidth: 720 }}>
      <div className="page-header">
        <div>
          <h1>Welcome to {settings.app.name}</h1>
          <p>Turn your notes, slides, and links into quizzes, study guides, and video playlists. Let's check that everything's ready.</p>
        </div>
      </div>

      <ErrorBanner error={error} compact />

      <section className="card">
        <div className="card-title">
          <h2><Terminal size={18} style={{ verticalAlign: -3, marginRight: 8 }} />Claude Code</h2>
          <button className="btn sm" onClick={recheck} disabled={checking || cli == null}>
            {checking ? <span className="spinner" /> : <RefreshCw size={14} />} Check again
          </button>
        </div>
        <p className="muted small">
          This app works with Claude Code, a separate program from Anthropic that you install yourself. It runs on your own
          Claude plan, so what you do here counts toward your plan's usage limits. This app never sees your password or sign-in.
        </p>

        <Check ok={!!cli?.installed} checking={checking || cli == null} title={cli?.installed ? `Claude Code is installed${cli.version ? ` (version ${cli.version.split(" ")[0]})` : ""}` : "Claude Code isn't installed yet"}>
          Follow <a href={docsUrl} target="_blank" rel="noreferrer">Anthropic's install instructions <ExternalLink size={12} style={{ verticalAlign: -1 }} /></a>,
          then come back here and click Check again. You need a Claude plan that includes Claude Code (the free plan doesn't).
        </Check>
        <Check ok={!!cli?.logged_in} checking={checking || cli == null} title={cli?.logged_in ? "You're signed in to Claude Code" : "You're not signed in to Claude Code yet"}>
          Open a terminal (PowerShell on Windows, Terminal on a Mac), type <code>claude</code>, press Enter, and follow the steps to sign in
          with your own Claude account in your browser. When it's done, type <code>/exit</code>, then come back and click Check again.
        </Check>
        {cli?.ready && cli.message && <p className="muted small" style={{ marginBottom: 0 }}>{cli.message}</p>}
      </section>

      <YoutubeKeyCard optionalNote />

      <section className="card">
        <h2><PlayCircle size={18} style={{ verticalAlign: -3, marginRight: 8 }} />See it working first</h2>
        <p className="muted small">
          Load a small sample Study Set on thermodynamics, with a breakdown, study guide, playlist, and a quiz you can take.
          You don't need to upload anything, and you can delete it any time. Questions in the sample quiz are graded right here, so they work even before Claude Code is set up.
        </p>
        <button className="btn" onClick={tryDemo} disabled={loadingDemo}>
          {loadingDemo ? <span className="spinner" /> : <PlayCircle size={15} />} Try a demo
        </button>
      </section>

      <div className="row" style={{ justifyContent: "flex-end", marginTop: 8 }}>
        <button className="btn primary" onClick={() => { void finish().then((ok) => { if (ok) navigate("/"); }); }}>
          {cli?.ready ? "Start studying" : "Finish later"}
        </button>
      </div>

      <p className="muted small" style={{ marginTop: 20 }}>
        {settings.app.name} is unofficial. It isn't affiliated with or endorsed by Anthropic.
      </p>
    </div>
  );
}
