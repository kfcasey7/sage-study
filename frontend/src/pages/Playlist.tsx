import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Copy, ExternalLink, ListVideo, PlusCircle, RefreshCw, Trash2 } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, PlaylistVideo, PlaylistView } from "../lib/types";
import { ErrorBanner, formatDate, InfoBanner, Loading } from "../components/common";
import { clock, openInBrowser, VideoCard, VideoPlayerDialog } from "../components/Videos";

export default function Playlist() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { toast } = useApp();
  const [view, setView] = useState<PlaylistView | null>(null);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [playing, setPlaying] = useState<PlaylistVideo | null>(null);
  const pollRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    if (pollRef.current) window.clearTimeout(pollRef.current);
    try {
      const v = await api.playlist(id);
      setView(v);
      if (v.status === "generating") pollRef.current = window.setTimeout(load, 2000);
    } catch (e) {
      setError(asApiError(e).toBody());
    }
  }, [id]);

  useEffect(() => {
    void load();
    return () => { if (pollRef.current) window.clearTimeout(pollRef.current); };
  }, [load]);

  async function act(key: string, fn: () => Promise<PlaylistView | void>) {
    setBusy(key);
    try {
      const v = await fn();
      if (v) setView(v);
    } catch (e) {
      toast(asApiError(e).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function toggleWatched(v: PlaylistVideo) {
    setView((p) => p && { ...p, groups: p.groups.map((g) => ({ ...g, videos: g.videos.map((x) => (x.id === v.id ? { ...x, watched: !v.watched } : x)) })) });
    try { await api.setWatched(v.id, !v.watched); } catch (e) { toast(asApiError(e).message, "error"); void load(); }
  }

  if (!view) {
    return error ? <div className="page"><ErrorBanner error={error} onRetry={() => void load()} /></div>
      : <Loading message="Opening your playlist…" rotate={false} />;
  }

  const all = view.groups.flatMap((g) => g.videos);
  const watched = all.filter((v) => v.watched).length;
  const totalSeconds = all.reduce((t, v) => t + (v.duration_s ?? 0), 0);

  async function copyLinks() {
    const text = view!.groups.map((g) => `${g.name}\n${g.videos.map((v) => `- ${v.title}: ${v.url}`).join("\n")}`).join("\n\n");
    try { await navigator.clipboard.writeText(text); toast("Links copied.", "success"); }
    catch { toast("Couldn't copy to the clipboard.", "error"); }
  }

  return (
    <div className="page wide">
      <Link to={`/sets/${view.set_id}`} className="btn ghost sm" style={{ marginBottom: 12 }}><ArrowLeft size={14} /> Back to {view.set_title || "study set"}</Link>
      <div className="page-header">
        <div>
          <h1><ListVideo size={26} style={{ verticalAlign: -4, color: "var(--primary)" }} /> Video playlist</h1>
          <p>
            {view.set_title} · {formatDate(view.created_at)}
            {all.length > 0 && ` · ${all.length} video${all.length === 1 ? "" : "s"}${totalSeconds ? ` (${clock(totalSeconds)})` : ""} · ${watched} watched`}
          </p>
        </div>
        {all.length > 0 && (
          <div className="row">
            {view.youtube_playlist_url && (
              <button className="btn sm" onClick={() => openInBrowser(view.youtube_playlist_url!, toast)}
                title="Opens all of these videos as one temporary playlist on YouTube">
                <ExternalLink size={15} /> Open as YouTube playlist
              </button>
            )}
            <button className="btn sm" onClick={() => void copyLinks()}><Copy size={15} /> Copy all links</button>
            <button className="btn sm ghost" onClick={() => act("delete", async () => { await api.deletePlaylist(id); toast("Playlist deleted."); navigate(`/sets/${view.set_id}`); })}
              title="Delete this playlist"><Trash2 size={15} /></button>
          </div>
        )}
      </div>

      {view.status === "generating" && (
        <div className="banner info">
          <span className="spinner" style={{ marginTop: 3 }} />
          <div className="banner-body">
            <div className="banner-title">Finding videos…</div>
            <div className="small">Searching YouTube for each subtopic, choosing the clearest explanations, and checking that every video exists.</div>
          </div>
        </div>
      )}
      {view.status === "failed" && <ErrorBanner error={view.error} />}
      {view.mode === "websearch" && view.status !== "generating" && (
        <InfoBanner title="Searching without a YouTube API key">
          Videos are found with Claude's web search, so lengths may be missing and results can be thinner. Add a free
          YouTube Data API key in <a href="#/settings">Settings</a> for better results.
        </InfoBanner>
      )}

      {view.groups.map((g) => (
        <section key={g.subtopic_id} className="card playlist-group">
          <div className="card-title">
            <h2 style={{ margin: 0 }}>{g.name}</h2>
            {view.status !== "generating" && (
              <button className="btn sm ghost" disabled={!!busy} onClick={() => act(`more-${g.subtopic_id}`, () => api.moreVideos(id, g.subtopic_id))}>
                {busy === `more-${g.subtopic_id}` ? <span className="spinner" /> : <PlusCircle size={14} />} Find more for this subtopic
              </button>
            )}
          </div>
          {view.status === "generating" && g.videos.length === 0 ? (
            <div className="video-grid">{[0, 1, 2].map((i) => <div key={i} className="skeleton" style={{ height: 200 }} />)}</div>
          ) : g.videos.length === 0 ? (
            <p className="muted small">No suitable videos were found for this subtopic. Try "Find more".</p>
          ) : (
            <div className="video-grid">
              {g.videos.map((v) => (
                <VideoCard key={v.id} video={v} onPlay={() => setPlaying(v)} dim={v.watched}>
                  <label className="watched-check">
                    <input type="checkbox" checked={v.watched} onChange={() => void toggleWatched(v)} /> Watched
                  </label>
                  <button className="btn sm ghost" disabled={!!busy} onClick={() => act(`replace-${v.id}`, () => api.replaceVideo(v.id))}>
                    {busy === `replace-${v.id}` ? <span className="spinner" /> : <RefreshCw size={13} />} Replace this video
                  </button>
                </VideoCard>
              ))}
            </div>
          )}
        </section>
      ))}

      {playing && <VideoPlayerDialog video={playing} onClose={() => setPlaying(null)} />}
    </div>
  );
}
