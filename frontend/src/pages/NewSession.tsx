import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpenCheck, ClipboardList, Layers, ListVideo, Sparkles } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, SourceView } from "../lib/types";
import { ErrorBanner, InfoBanner, Loading } from "../components/common";
import { SourceAdder, SourceCard } from "../components/Sources";

function newDraftId(): string {
  try { return crypto.randomUUID(); } catch { return `${Date.now()}-${Math.random().toString(36).slice(2)}`; }
}

/** Setup: what to cover and the sources (files and links). Creating the set builds its Material Breakdown,
 *  where you choose to make a study guide, take a quiz, or build a video playlist. */
export default function NewSession() {
  const { settings, cli, bumpHistory } = useApp();
  const navigate = useNavigate();
  const [draftId] = useState(newDraftId);
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [subject, setSubject] = useState("");
  const [subjects, setSubjects] = useState<string[]>([]);
  const [sources, setSources] = useState<SourceView[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => { api.subjects().then(setSubjects).catch(() => setSubjects([])); }, []);

  // Links are read in the background: poll until each is ready or couldn't be read.
  const processing = sources.filter((s) => s.status === "processing").map((s) => s.id);
  const processingKey = processing.join(",");
  useEffect(() => {
    if (!processingKey) return;
    const t = window.setInterval(() => {
      api.sources(processingKey.split(",")).then((rows) => {
        const byId = new Map(rows.map((r) => [r.id, r]));
        setSources((list) => list.map((s) => byId.get(s.id) ?? s));
      }).catch(() => { /* try again next tick */ });
    }, 1500);
    return () => window.clearInterval(t);
  }, [processingKey]);

  if (!settings) return <Loading message="Getting things ready…" rotate={false} />;
  const usable = sources.filter((s) => s.status !== "failed");
  const canCreate = !creating && (prompt.trim().length > 0 || usable.length > 0);

  function remove(s: SourceView) {
    setSources((list) => list.filter((x) => x.id !== s.id));
    api.deleteSource(s.id).catch(() => { /* removed at the next startup cleanup */ });
  }

  async function retry(s: SourceView) {
    try {
      const r = await api.retrySource(s.id);
      setSources((list) => list.map((x) => (x.id === s.id ? r : x)));
    } catch (e) { setError(asApiError(e).toBody()); }
  }

  async function create() {
    setCreating(true);
    setError(null);
    try {
      const set = await api.createSet({ title, subject, prompt, source_ids: usable.map((s) => s.id) });
      // Unreadable links stay out of the set; drop them now rather than at the next cleanup.
      sources.filter((s) => s.status === "failed").forEach((s) => api.deleteSource(s.id).catch(() => undefined));
      bumpHistory();
      navigate(`/sets/${set.id}`);
    } catch (e) {
      setError(asApiError(e).toBody());
      setCreating(false);
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>New study set</h1>
          <p>Tell Sage what to cover and add your notes, slides, and links. You'll get a breakdown of the material, then choose what to do with it.</p>
        </div>
      </div>

      {cli && !cli.ready && (
        <InfoBanner tone="warn" title="Claude Code needs attention">
          {cli.message} <a href="#/settings">Open Settings</a> for details.
        </InfoBanner>
      )}
      <ErrorBanner error={error} onRetry={create} />

      <section className="card stack">
        <div className="grid-2">
          <label className="field">
            Title <span className="field-hint">Optional. Sage suggests one from your material.</span>
            <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Midterm 2 review" maxLength={120} />
          </label>
          <label className="field">
            Subject <span className="field-hint">Optional. Used to track your mastery over time.</span>
            <input className="input" list="subjects" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="e.g. Signals & Systems" maxLength={80} />
            <datalist id="subjects">{subjects.map((s) => <option key={s} value={s} />)}</datalist>
          </label>
        </div>
        <label className="field">
          What should this study set cover?
          <span className="field-hint">A topic, chapter, or learning objectives. Be as specific as you like. You can add more later.</span>
          <textarea className="textarea" rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)}
            placeholder={"e.g. Chapter 4: Laplace transforms. Focus on partial fractions, initial/final value theorems, and solving RLC circuits."} />
        </label>

        <div>
          <div className="field" style={{ marginBottom: 6 }}>Sources <span className="field-hint">Files and links. Pages that need a login can't be read; upload the file instead.</span></div>
          <SourceAdder scope={{ draft_id: draftId }} onAdded={(added) => setSources((list) => [...list, ...added])} inputRef={fileInput} />
          {sources.length > 0 && (
            <div className="source-list">
              {sources.map((s) => (
                <SourceCard key={s.id} source={s} onRemove={() => remove(s)} onRetry={() => void retry(s)}
                  onUploadInstead={() => fileInput.current?.click()} />
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="card next-steps">
        <h3 style={{ marginTop: 0 }}>What happens next</h3>
        <div className="next-grid">
          <div><Layers size={18} /> <span><strong>Material Breakdown:</strong> an overview, subtopics with key concepts and formulas, and a map of how they connect.</span></div>
          <div><BookOpenCheck size={18} /> <span><strong>Study guide</strong> for the subtopics you pick.</span></div>
          <div><ClipboardList size={18} /> <span><strong>Quiz</strong> with the question types and difficulty you choose.</span></div>
          <div><ListVideo size={18} /> <span><strong>Video playlist</strong> of YouTube explanations for each subtopic.</span></div>
        </div>
      </section>

      <div className="row" style={{ marginTop: 22, justifyContent: "flex-end" }}>
        {processing.length > 0 && <span className="muted small">Links still being read are included once they're ready.</span>}
        <button className="btn primary lg" disabled={!canCreate} onClick={create}>
          {creating ? <span className="spinner" /> : <Sparkles size={18} />} Create study set
        </button>
      </div>
      {!prompt.trim() && usable.length === 0 && (
        <div className="muted small" style={{ textAlign: "right", marginTop: 8 }}>
          Describe what to cover or add a file or link to begin.
        </div>
      )}
    </div>
  );
}
