import { useEffect, useState } from "react";
import { Download, Globe, Power, X } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, UpdateState } from "../lib/types";
import { ErrorBanner } from "./common";

/** Shown when the app runs in a browser tab because its own window couldn't start. The tab reports in
 *  regularly; the app closes itself a few minutes after the tab goes away. */
export function BrowserModeBanner() {
  const { settings } = useApp();
  const [stopped, setStopped] = useState(false);
  const mode = settings?.app.window_mode;
  const seconds = settings?.app.heartbeat_seconds ?? 20;

  useEffect(() => {
    if (mode !== "browser") return;
    void api.heartbeat().catch(() => { /* try again next tick */ });
    const t = window.setInterval(() => { void api.heartbeat().catch(() => { /* the app has closed */ }); }, seconds * 1000);
    return () => window.clearInterval(t);
  }, [mode, seconds]);

  if (mode !== "browser") return null;
  if (stopped) {
    return <div className="page"><div className="banner info"><Power size={20} /><div className="banner-body">{settings?.app.name} has closed. You can close this tab.</div></div></div>;
  }
  return (
    <div className="banner info" style={{ margin: "12px 16px 0" }}>
      <Globe size={20} />
      <div className="banner-body small">
        <div className="banner-title">Running in your browser</div>
        {settings?.app.fallback_reason === "you asked for the browser version"
          ? "You asked to use the browser version."
          : "The app's own window couldn't open on this computer, so it opened here instead. Everything works the same, and everything still stays on your computer."}
        {" "}It closes by itself a few minutes after you close this tab.
      </div>
      <button className="btn sm" onClick={() => { void api.quit().then(() => setStopped(true)); }}><Power size={14} /> Quit</button>
    </div>
  );
}

/** A quiet note when a newer release exists. Nothing updates until you click, and it can be turned off in Settings. */
export function UpdateBanner() {
  const { settings } = useApp();
  const [update, setUpdate] = useState<UpdateState | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [showNotes, setShowNotes] = useState(false);
  const [busy, setBusy] = useState(false);
  const [command, setCommand] = useState<string | null>(null);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const enabled = settings?.settings.update_check;

  useEffect(() => {
    if (enabled) api.updates().then(setUpdate).catch(() => { /* no banner */ });
  }, [enabled]);

  if (!update || update.status !== "available" || dismissed) return null;

  async function apply() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.applyUpdate();
      if (r.action === "manual") setCommand(r.command ?? null);
    } catch (e) {
      setError(asApiError(e).toBody());
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="banner info" style={{ margin: "12px 16px 0" }}>
      <Download size={20} />
      <div className="banner-body small">
        <div className="banner-title">{settings?.app.name} {update.latest} is available</div>
        <div>
          You have version {update.current}.{" "}
          <button className="btn sm ghost" style={{ padding: "0 4px" }} onClick={() => setShowNotes((v) => !v)}>{showNotes ? "Hide" : "What's new"}</button>
        </div>
        {showNotes && <div style={{ whiteSpace: "pre-wrap", marginTop: 8, maxHeight: 220, overflow: "auto" }}>{update.notes || "No release notes."}</div>}
        {command && <div style={{ marginTop: 8 }}>To update, run: <code>{command}</code></div>}
        <ErrorBanner error={error} compact />
      </div>
      {!command && (
        <button className="btn sm primary" onClick={apply} disabled={busy}>
          {busy ? <span className="spinner" /> : <Download size={14} />} {update.can_self_update ? "Update and restart" : update.install_kind === "packaged" ? "Open download page" : "Update"}
        </button>
      )}
      <button className="icon-btn" onClick={() => setDismissed(true)} aria-label="Dismiss"><X size={16} /></button>
    </div>
  );
}
