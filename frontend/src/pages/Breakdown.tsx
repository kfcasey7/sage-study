import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle, BookOpenCheck, Check, ClipboardList, FileWarning, History as HistoryIcon, Layers, ListVideo, Network,
  PlusCircle, RefreshCw, Sparkles, X,
} from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, SetSubtopic, SourceView, StudySetView } from "../lib/types";
import { ErrorBanner, formatDate, formatDateTime, Loading, scoreColor } from "../components/common";
import { Formula } from "../components/Formula";
import { Markdown } from "../components/Markdown";
import { MermaidDiagram } from "../components/MermaidDiagram";
import { StartQuizDialog } from "../components/QuizOptions";
import { SetMenu } from "../components/SetMenu";
import { SourceAdder, SourceCard } from "../components/Sources";

function SubtopicCard({ s, checked, onToggle, sources }: {
  s: SetSubtopic; checked: boolean; onToggle: () => void; sources: Map<string, SourceView>;
}) {
  const { settings } = useApp();
  const level = s.difficulty ? settings?.options.difficulty_levels[String(s.difficulty)]?.label : null;
  const m = s.mastery;
  return (
    <div className={`subtopic-card ${checked ? "on" : ""}`}>
      <label className="subtopic-check">
        <input type="checkbox" checked={checked} onChange={onToggle} aria-label={`Include ${s.name}`} />
      </label>
      <div className="subtopic-main">
        <div className="subtopic-head">
          <h3>{s.name}</h3>
          {s.is_new && <span className="badge primary"><Sparkles size={12} /> New</span>}
          {s.is_updated && <span className="badge">Updated</span>}
          <span className="spacer" />
          {level && <span className="badge" title="Estimated difficulty">Level {s.difficulty} · {level}</span>}
          {m && m.score != null && (
            <span className="badge mastery" style={{ color: scoreColor(m.score), borderColor: scoreColor(m.score) }}
              title={`${m.correct} correct, ${m.partial} partial, ${m.incorrect} incorrect across your quizzes`}>
              Mastery {Math.round(m.score)}% · {m.n} Q{m.n === 1 ? "" : "s"}
            </span>
          )}
        </div>
        <Markdown className="subtopic-summary">{s.summary}</Markdown>
        {s.key_concepts.length > 0 && (
          <div className="concepts">{s.key_concepts.map((c) => <span key={c} className="concept">{c}</span>)}</div>
        )}
        {s.formulas.length > 0 && (
          <div className="subtopic-formulas">
            {s.formulas.map((f, i) => (
              <div key={i} className="mini-formula" title={f.description}>
                <Formula latex={f.latex} inline />
                <span className="muted small">{f.description}</span>
              </div>
            ))}
          </div>
        )}
        {s.source_ids.length > 0 && (
          <div className="subtopic-sources">
            From {s.source_ids.map((id) => sources.get(id)).filter(Boolean).map((src) => (
              <span key={src!.id} className="source-chip" title={src!.title}>{src!.label}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function statusLabel(status: string, score: number | null) {
  if (status === "completed") return score != null ? `${Math.round(score)}%` : "Completed";
  return "In progress";
}

export default function Breakdown() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { toast, bumpHistory } = useApp();
  const [view, setView] = useState<StudySetView | null>(null);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const [deselected, setDeselected] = useState<Set<string>>(new Set());
  const [quizOpen, setQuizOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [appendPrompt, setAppendPrompt] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [mapFailed, setMapFailed] = useState(false);
  const pollRef = useRef<number | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    if (pollRef.current) window.clearTimeout(pollRef.current);
    try {
      const v = await api.set(id);
      setView((prev) => {
        // Something finished in the background: refresh the sidebar and History.
        if (prev && prev.breakdown.status === "generating" && v.breakdown.status !== "generating") bumpHistory();
        return v;
      });
      setError(null);
      const busyNow = v.breakdown.status === "generating" || v.sources.some((s) => s.status === "processing")
        || v.guides.some((g) => g.status === "generating") || v.playlists.some((p) => p.status === "generating");
      if (busyNow) pollRef.current = window.setTimeout(load, 2000);
      return v;
    } catch (e) {
      setError(asApiError(e).toBody());
      return null;
    }
  }, [id, bumpHistory]);

  useEffect(() => {
    setView(null);
    setDeselected(new Set());
    setMapFailed(false);
    void load();
    return () => { if (pollRef.current) window.clearTimeout(pollRef.current); };
  }, [id, load]);

  const sourceMap = useMemo(() => new Map((view?.sources ?? []).map((s) => [s.id, s])), [view?.sources]);
  const repairMap = useCallback((message: string) => {
    api.repairMap(id, message).then(() => load()).catch(() => setMapFailed(true));
  }, [id, load]);

  if (!view) {
    return error
      ? <div className="page"><ErrorBanner error={error} onRetry={() => void load()} /></div>
      : <Loading message="Opening your study set…" rotate={false} />;
  }

  const bd = view.breakdown;
  const generating = bd.status === "generating";
  const selected = view.subtopics.filter((s) => !deselected.has(s.id));
  const canAct = selected.length > 0 && !generating && !busy;
  const toggle = (sid: string) => setDeselected((d) => { const n = new Set(d); if (n.has(sid)) n.delete(sid); else n.add(sid); return n; });

  async function run(kind: string, fn: () => Promise<void>) {
    setBusy(kind);
    try { await fn(); } catch (e) { toast(asApiError(e).message, "error"); } finally { setBusy(null); }
  }

  const startGuide = () => run("guide", async () => {
    const g = await api.startSetGuide(id, selected.map((s) => s.id));
    bumpHistory();
    navigate(`/study-guides/${g.id}`);
  });
  const startPlaylist = () => run("playlist", async () => {
    const p = await api.startPlaylist(id, selected.map((s) => s.id));
    bumpHistory();
    navigate(`/playlists/${p.id}`);
  });
  const rebuild = () => run("rebuild", async () => { setView(await api.buildBreakdown(id)); setMapFailed(false); void load(); });
  const append = () => run("append", async () => {
    setView(await api.appendToSet(id, appendPrompt));
    setAppendPrompt("");
    setMapFailed(false);
    toast("Updating the breakdown with your additions…");
    void load();
  });
  const saveTitle = () => run("title", async () => {
    setView(await api.updateSet(id, { title: titleDraft }));
    setRenaming(false);
    bumpHistory();
  });

  function onSourcesAdded() { void load(); }
  async function removeSource(s: SourceView) {
    try { await api.deleteSource(s.id); void load(); } catch (e) { toast(asApiError(e).message, "error"); }
  }
  async function retrySource(s: SourceView) {
    try { await api.retrySource(s.id); void load(); } catch (e) { toast(asApiError(e).message, "error"); }
  }

  const hasNewMaterial = view.sources_changed || view.sources.some((s) => s.status === "processing");

  return (
    <div className="page wide breakdown-page">
      <div className="page-header">
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="eyebrow"><Layers size={14} /> Material Breakdown</div>
          {renaming ? (
            <div className="row">
              <input className="input" autoFocus value={titleDraft} maxLength={120} style={{ maxWidth: 520, fontSize: "1.2rem" }}
                onChange={(e) => setTitleDraft(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void saveTitle(); if (e.key === "Escape") setRenaming(false); }} />
              <button className="btn sm primary" onClick={() => void saveTitle()} disabled={!titleDraft.trim()}><Check size={14} /> Save</button>
              <button className="btn sm ghost" onClick={() => setRenaming(false)}><X size={14} /> Cancel</button>
            </div>
          ) : (
            <h1>{view.title || (generating ? "New study set" : "Study set")}</h1>
          )}
          <p>
            {view.subject ? `${view.subject} · ` : ""}{view.sources.length} source{view.sources.length === 1 ? "" : "s"}
            {" "}· {view.subtopics.length} subtopic{view.subtopics.length === 1 ? "" : "s"} · created {formatDate(view.created_at)}
          </p>
        </div>
        <SetMenu setId={id} onRename={() => { setTitleDraft(view.title); setRenaming(true); }} />
      </div>

      {bd.status === "failed" && (
        <ErrorBanner error={bd.error ?? { code: "server_error", message: "Building the breakdown failed." }} onRetry={rebuild} />
      )}
      {generating && (
        <div className="banner info">
          <span className="spinner" style={{ marginTop: 3 }} />
          <div className="banner-body">
            <div className="banner-title">{view.subtopics.length > 0 ? "Updating the breakdown…" : "Breaking down your material…"}</div>
            <div className="small">Claude is reading {view.sources.filter((s) => s.status !== "failed").length || "your"} source{view.sources.length === 1 ? "" : "s"} and mapping the subtopics. This usually takes a minute or two.</div>
          </div>
        </div>
      )}
      {bd.status === "legacy" && (
        <div className="banner info">
          <Layers size={20} />
          <div className="banner-body">
            <div className="banner-title">This study set was made before Material Breakdowns</div>
            <div className="small">Its subtopics come from your earlier quiz. Build the full breakdown to add an overview, key concepts, formulas, a map, and coverage notes. Your quiz results stay attached.</div>
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn sm primary" onClick={rebuild} disabled={!!busy}>{busy === "rebuild" ? <span className="spinner" /> : <Sparkles size={14} />} Build full breakdown</button>
            </div>
          </div>
        </div>
      )}
      {view.sources_changed && !generating && bd.status !== "legacy" && (
        <div className="banner warn">
          <RefreshCw size={20} />
          <div className="banner-body">
            Your sources changed since this breakdown was built.
            <button className="btn sm" style={{ marginLeft: 10 }} onClick={append} disabled={!!busy}>Update breakdown</button>
          </div>
        </div>
      )}

      <div className="breakdown-grid">
        <div className="breakdown-main">
          {(bd.overview || generating && !view.subtopics.length) && (
            <section className="card">
              <h2 style={{ marginTop: 0 }}>Overview</h2>
              {bd.overview ? <Markdown>{bd.overview}</Markdown> : <div className="stack"><div className="skeleton" style={{ height: 16 }} /><div className="skeleton" style={{ height: 16, width: "80%" }} /></div>}
              {bd.coverage_notes.length > 0 && (
                <div className="coverage">
                  <div className="coverage-title"><FileWarning size={16} /> Not covered by your sources</div>
                  <ul>{bd.coverage_notes.map((n, i) => <li key={i}><Markdown>{n}</Markdown></li>)}</ul>
                </div>
              )}
              {bd.unreadable_sources.length > 0 && (
                <div className="muted small" style={{ marginTop: 10 }}>
                  <AlertTriangle size={13} style={{ verticalAlign: -2 }} /> Left out because they couldn't be read: {bd.unreadable_sources.join(", ")}
                </div>
              )}
              {bd.removed.length > 0 && (
                <div className="muted small" style={{ marginTop: 6 }}>Removed in the last update: {bd.removed.join(", ")}. Past quiz results on them are kept.</div>
              )}
            </section>
          )}

          <section className="card">
            <div className="card-title">
              <h2 style={{ margin: 0 }}>Subtopics</h2>
              {view.subtopics.length > 0 && (
                <div className="row">
                  <span className="muted small">{selected.length} of {view.subtopics.length} selected</span>
                  <button className="btn sm ghost" onClick={() => setDeselected(new Set())}>Select all</button>
                  <button className="btn sm ghost" onClick={() => setDeselected(new Set(view.subtopics.map((s) => s.id)))}>Select none</button>
                </div>
              )}
            </div>
            {view.subtopics.length === 0 ? (
              generating ? <div className="stack">{[0, 1, 2].map((i) => <div key={i} className="skeleton" style={{ height: 84 }} />)}</div>
                : <p className="muted">No subtopics yet.</p>
            ) : (
              <div className="subtopic-list">
                {view.subtopics.map((s) => (
                  <SubtopicCard key={s.id} s={s} checked={!deselected.has(s.id)} onToggle={() => toggle(s.id)} sources={sourceMap} />
                ))}
              </div>
            )}
          </section>

          {view.subtopics.length > 0 && (
            <div className="action-bar">
              <div className="action-bar-label">
                {selected.length === 0 ? "Select at least one subtopic" : `For ${selected.length === view.subtopics.length ? "all" : selected.length} subtopic${selected.length === 1 ? "" : "s"}:`}
              </div>
              <button className="btn primary" disabled={!canAct} onClick={startGuide}>
                {busy === "guide" ? <span className="spinner" /> : <BookOpenCheck size={17} />} Generate study guide
              </button>
              <button className="btn primary" disabled={!canAct} onClick={() => setQuizOpen(true)}>
                <ClipboardList size={17} /> Start quiz
              </button>
              <button className="btn primary" disabled={!canAct} onClick={startPlaylist}>
                {busy === "playlist" ? <span className="spinner" /> : <ListVideo size={17} />} Build video playlist
              </button>
            </div>
          )}

          {bd.map_mermaid && (
            <section className="card">
              <h2 style={{ marginTop: 0 }}><Network size={18} style={{ verticalAlign: -3 }} /> How the subtopics connect</h2>
              {mapFailed ? (
                <ul>{view.subtopics.map((s) => <li key={s.id}>{s.name}</li>)}</ul>
              ) : (
                <MermaidDiagram code={bd.map_mermaid} onError={bd.map_repaired ? () => setMapFailed(true) : repairMap} />
              )}
            </section>
          )}
        </div>

        <aside className="breakdown-side">
          <section className="card">
            <h2 style={{ marginTop: 0 }}>Sources</h2>
            {view.sources.length === 0 && <p className="muted small">No files or links. The breakdown is based on your prompts and general course knowledge.</p>}
            <div className="source-list" style={{ marginTop: 0 }}>
              {view.sources.map((s) => (
                <SourceCard key={s.id} source={s} showLabel onRemove={() => void removeSource(s)} onRetry={() => void retrySource(s)}
                  onUploadInstead={() => uploadRef.current?.click()} />
              ))}
            </div>
          </section>

          <section className="card append-panel">
            <h2 style={{ marginTop: 0 }}><PlusCircle size={18} style={{ verticalAlign: -3 }} /> Append to this study set</h2>
            <label className="field">
              Add a prompt
              <textarea className="textarea" rows={3} value={appendPrompt} onChange={(e) => setAppendPrompt(e.target.value)} maxLength={4000}
                placeholder={'e.g. "also cover chapter 7" or "focus more on Laplace transforms"'} />
            </label>
            <div className="field" style={{ marginBottom: 6 }}>Add files or links</div>
            <SourceAdder scope={{ set_id: id }} onAdded={onSourcesAdded} compact inputRef={uploadRef} />
            <button className="btn primary" style={{ marginTop: 12, width: "100%" }} onClick={append}
              disabled={!!busy || generating || (!appendPrompt.trim() && !hasNewMaterial)}>
              {busy === "append" ? <span className="spinner" /> : <RefreshCw size={16} />} Update breakdown
            </button>
            <div className="muted small" style={{ marginTop: 6 }}>Existing subtopics stay put and keep your quiz results; new ones are marked <strong>New</strong>.</div>

            {view.prompts.length > 0 && (
              <div className="prompt-history">
                <div className="field" style={{ marginBottom: 6 }}><HistoryIcon size={14} style={{ verticalAlign: -2 }} /> Prompt history</div>
                <ol>
                  {view.prompts.map((p) => (
                    <li key={p.id}><div className="prompt-text">{p.text}</div><div className="muted small">{formatDateTime(p.created_at)}</div></li>
                  ))}
                </ol>
              </div>
            )}
          </section>

          <section className="card">
            <h2 style={{ marginTop: 0 }}>Made from this set</h2>
            {view.quizzes.length + view.guides.length + view.playlists.length === 0 && <p className="muted small">Quizzes, study guides, and playlists you make will be listed here.</p>}
            {view.quizzes.length > 0 && <h3 className="made-head"><ClipboardList size={14} /> Quizzes</h3>}
            {view.quizzes.map((q) => (
              <Link key={q.id} className="made-row" to={q.status === "completed" ? `/results/${q.id}` : `/quiz/${q.id}`}>
                <span className="made-title">{q.parent_session_id ? "Retest" : "Quiz"} · {q.subtopics.length} subtopic{q.subtopics.length === 1 ? "" : "s"} · {q.count ?? "?"} Qs</span>
                <span className="made-meta" style={q.status === "completed" && q.score != null ? { color: scoreColor(q.score), fontWeight: 650 } : undefined}>
                  {statusLabel(q.status, q.score)}
                </span>
                <span className="made-date">{formatDate(q.created_at)}</span>
              </Link>
            ))}
            {view.guides.length > 0 && <h3 className="made-head"><BookOpenCheck size={14} /> Study guides</h3>}
            {view.guides.map((g) => (
              <Link key={g.id} className="made-row" to={g.kind === "weak_areas" && g.session_id ? `/guide/${g.session_id}` : `/study-guides/${g.id}`}>
                <span className="made-title">{g.kind === "weak_areas" ? "Weak areas" : g.subtopics.join(", ")}</span>
                <span className="made-meta">{g.status === "generating" ? "Writing…" : g.status === "failed" ? "Failed" : ""}</span>
                <span className="made-date">{formatDate(g.created_at)}</span>
              </Link>
            ))}
            {view.playlists.length > 0 && <h3 className="made-head"><ListVideo size={14} /> Video playlists</h3>}
            {view.playlists.map((p) => (
              <Link key={p.id} className="made-row" to={`/playlists/${p.id}`}>
                <span className="made-title">{p.subtopics.join(", ")}</span>
                <span className="made-meta">{p.status === "generating" ? "Finding videos…" : p.status === "failed" ? "Failed" : `${p.watched}/${p.videos} watched`}</span>
                <span className="made-date">{formatDate(p.created_at)}</span>
              </Link>
            ))}
          </section>
        </aside>
      </div>

      {quizOpen && <StartQuizDialog setId={id} subtopics={selected} onClose={() => setQuizOpen(false)} />}
    </div>
  );
}
