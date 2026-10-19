import { useEffect, useState } from "react";
import { CheckCircle2, KeyRound, Trash2 } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, YoutubeKeyStatus } from "../lib/types";
import { ErrorBanner } from "./common";

/** Optional YouTube Data API key, kept in the system credential store. Without one, videos are found with
 *  Claude's web search. */
export function YoutubeKeyCard() {
  const { toast } = useApp();
  const [status, setStatus] = useState<YoutubeKeyStatus | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiErrorBody | null>(null);

  useEffect(() => { api.youtubeKey().then(setStatus).catch((e) => setError(asApiError(e).toBody())); }, []);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      setStatus(await api.saveYoutubeKey(draft.trim()));
      setDraft("");
      toast("YouTube API key saved and working.", "success");
    } catch (e) {
      setError(asApiError(e).toBody());
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    try { setStatus(await api.deleteYoutubeKey()); toast("YouTube API key removed."); }
    catch (e) { setError(asApiError(e).toBody()); }
  }

  return (
    <section className="card">
      <h2><KeyRound size={18} style={{ verticalAlign: -3, marginRight: 8 }} />YouTube videos</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        Video playlists and "Find video" search YouTube for explanations. With a free <strong>YouTube Data API</strong> key,
        searches are faster and show each video's length and view count. Without one, Sage uses Claude's web search
        (limited to youtube.com). Every video is checked to exist before it's shown either way.
      </p>
      <ErrorBanner error={error} compact />
      {status?.set ? (
        <div className="row">
          <CheckCircle2 size={18} color="var(--correct)" />
          <span style={{ fontWeight: 600 }}>Key saved</span>
          <span className="muted small">ending in ··{status.last4} · stored in your system's credential manager</span>
          <span className="spacer" />
          <button className="btn sm ghost danger" onClick={() => void remove()}><Trash2 size={14} /> Remove</button>
        </div>
      ) : (
        <>
          <div className="row">
            <input className="input" type="password" autoComplete="off" spellCheck={false} value={draft} onChange={(e) => setDraft(e.target.value)}
              placeholder="Paste a YouTube Data API v3 key (starts with AIza…)" style={{ flex: 1, minWidth: 260 }}
              onKeyDown={(e) => { if (e.key === "Enter" && draft.trim()) void save(); }} aria-label="YouTube API key" />
            <button className="btn primary" onClick={() => void save()} disabled={!draft.trim() || saving}>
              {saving && <span className="spinner" />} Test &amp; save
            </button>
          </div>
          <details className="small" style={{ marginTop: 10 }}>
            <summary>How to get a key (about 5 minutes, free)</summary>
            <ol style={{ marginBottom: 0 }}>
              <li>Go to console.cloud.google.com and sign in with a Google account.</li>
              <li>Create a project (any name).</li>
              <li>Open <strong>APIs &amp; Services → Library</strong>, find <strong>YouTube Data API v3</strong>, and click <strong>Enable</strong>.</li>
              <li>Open <strong>APIs &amp; Services → Credentials → Create credentials → API key</strong>, and copy the key.</li>
              <li>Optional: restrict the key to the YouTube Data API v3. Paste it above.</li>
            </ol>
            <p className="muted" style={{ marginBottom: 0 }}>The free quota (10,000 units a day) covers roughly 25-40 playlists or Find video searches a day; results are cached.</p>
          </details>
        </>
      )}
    </section>
  );
}
