import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { CirclePlay, ExternalLink, Video, X } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, QuestionVideos, VideoInfo } from "../lib/types";
import { ErrorBanner } from "./common";

export function clock(seconds: number | null | undefined): string {
  if (!seconds) return "";
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

export function openInBrowser(url: string, toast: (m: string, t?: "success" | "error") => void) {
  api.openUrl(url).then((r) => { if (!r.ok) toast("Couldn't open your browser.", "error"); })
    .catch((e) => toast(asApiError(e).message, "error"));
}

/** YouTube's privacy-enhanced embed. Embeds need a referrer, so the page's origin is sent. */
export function EmbeddedPlayer({ videoId, autoplay = true }: { videoId: string; autoplay?: boolean }) {
  const origin = encodeURIComponent(window.location.origin);
  return (
    <div className="player-frame">
      <iframe
        src={`https://www.youtube-nocookie.com/embed/${videoId}?rel=0&modestbranding=1&playsinline=1${autoplay ? "&autoplay=1" : ""}&origin=${origin}`}
        title="YouTube video player"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
        referrerPolicy="strict-origin-when-cross-origin"
        allowFullScreen
      />
    </div>
  );
}

/** Watch a video inside the app, with "Open in browser" if the embedded player doesn't work. */
export function VideoPlayerDialog({ video, onClose }: { video: VideoInfo; onClose: () => void }) {
  const { toast } = useApp();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal player-modal" role="dialog" aria-modal="true" aria-label={video.title}>
        <div className="modal-head">
          <div style={{ minWidth: 0 }}>
            <h2 style={{ margin: 0, fontSize: "1.05rem" }}>{video.title}</h2>
            <div className="muted small">{video.channel}{video.duration_s ? ` · ${clock(video.duration_s)}` : ""}</div>
          </div>
          <div className="row" style={{ flexShrink: 0 }}>
            <button className="btn sm" onClick={() => openInBrowser(video.url, toast)}><ExternalLink size={14} /> Open in browser</button>
            <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
          </div>
        </div>
        <EmbeddedPlayer videoId={video.video_id} />
        <div className="muted small player-note">If the video doesn't play here, use <strong>Open in browser</strong>.</div>
      </div>
    </div>,
    document.body,
  );
}

/** Thumbnail, title, channel, length, and Claude's one line on why it's relevant. */
export function VideoCard({ video, onPlay, children, compact = false, dim = false }: {
  video: VideoInfo; onPlay: () => void; children?: ReactNode; compact?: boolean; dim?: boolean;
}) {
  return (
    <div className={`video-card ${compact ? "compact" : ""} ${dim ? "dim" : ""}`}>
      <button className="video-thumb" onClick={onPlay} aria-label={`Play ${video.title}`}>
        <img src={video.thumbnail} alt="" loading="lazy" />
        <span className="video-play"><CirclePlay size={compact ? 26 : 34} /></span>
        {video.duration_s ? <span className="video-duration">{clock(video.duration_s)}</span> : null}
      </button>
      <div className="video-main">
        <button className="video-title" onClick={onPlay}>{video.title}</button>
        <div className="video-channel">{video.channel}</div>
        {video.reason && <div className="video-reason">{video.reason}</div>}
        {children && <div className="video-actions">{children}</div>}
      </div>
    </div>
  );
}

/** "Find video" side panel during a quiz. Opening it before answering is recorded as help (grades don't change). */
export function VideoPanel({ questionId, answered, onClose }: { questionId: string; answered: boolean; onClose: () => void }) {
  const { toast } = useApp();
  const [data, setData] = useState<QuestionVideos | null>(null);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const [playing, setPlaying] = useState<VideoInfo | null>(null);
  const current = useRef(questionId);

  async function find(qid: string) {
    setError(null);
    try {
      const existing = await api.questionVideos(qid);
      const out = existing.videos.length ? existing : await api.findQuestionVideos(qid);
      if (current.current === qid) setData(out);
    } catch (e) {
      if (current.current === qid) setError(asApiError(e).toBody());
    }
  }

  useEffect(() => {
    current.current = questionId;
    setData(null);
    setPlaying(null);
    void find(questionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionId]);

  return createPortal(
    <section className="chat-panel video-panel" role="dialog" aria-label="Videos about this question"
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
      <header className="chat-head">
        <div style={{ minWidth: 0 }}>
          <div className="chat-title"><Video size={17} /> Videos on this concept</div>
          <div className="chat-note">
            {answered || (data && !data.used_before_answer)
              ? "Watch these to review the idea behind this question."
              : "Looking at videos before answering is noted as \"used help\" on your results. Your grade doesn't change."}
          </div>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close videos"><X size={18} /></button>
      </header>
      <div className="chat-list">
        {playing && (
          <div className="panel-player">
            <EmbeddedPlayer videoId={playing.video_id} />
            <div className="row" style={{ justifyContent: "space-between", marginTop: 6 }}>
              <button className="btn sm ghost" onClick={() => setPlaying(null)}><X size={14} /> Close player</button>
              <button className="btn sm" onClick={() => openInBrowser(playing.url, toast)}><ExternalLink size={14} /> Open in browser</button>
            </div>
          </div>
        )}
        {!data && !error && (
          <div className="stack">
            <div className="row muted small"><span className="spinner" /> Searching YouTube and checking each video…</div>
            {[0, 1, 2].map((i) => <div key={i} className="skeleton" style={{ height: 76 }} />)}
          </div>
        )}
        {error && <ErrorBanner error={error} compact onRetry={() => void find(questionId)} />}
        {data?.videos.map((v) => (
          <VideoCard key={v.video_id} video={v} compact onPlay={() => setPlaying(v)}>
            <button className="btn sm ghost" onClick={() => openInBrowser(v.url, toast)}><ExternalLink size={13} /> Browser</button>
          </VideoCard>
        ))}
      </div>
    </section>,
    document.body,
  );
}
