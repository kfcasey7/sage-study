import { useEffect, useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, FileImage, FileText, Presentation, Sparkles, Upload, X } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, UploadInfo } from "../lib/types";
import { ErrorBanner, InfoBanner, Loading } from "../components/common";

interface LocalFile {
  key: string;
  name: string;
  size: number;
  status: "uploading" | "ready" | "error";
  info?: UploadInfo;
  error?: string;
}

interface Prefs { types: string[]; difficulty: number; adaptive: boolean; count: number; language: string }
const DEFAULT_PREFS: Prefs = { types: ["multiple_choice", "true_false", "short_response"], difficulty: 3, adaptive: false, count: 10, language: "Python" };

function loadPrefs(): Prefs {
  try { return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem("sage-new-session") || "{}") }; } catch { return DEFAULT_PREFS; }
}

function fileIcon(name: string) {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (["png", "jpg", "jpeg"].includes(ext)) return <FileImage size={18} />;
  if (ext === "pptx") return <Presentation size={18} />;
  return <FileText size={18} />;
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function NewSession() {
  const { settings, bumpHistory } = useApp();
  const navigate = useNavigate();
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [material, setMaterial] = useState("");
  const [subject, setSubject] = useState("");
  const [subjects, setSubjects] = useState<string[]>([]);
  const [files, setFiles] = useState<LocalFile[]>([]);
  const [drag, setDrag] = useState(false);
  const [customCount, setCustomCount] = useState(!([5, 10, 15, 20].includes(loadPrefs().count)));
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { api.subjects().then(setSubjects).catch(() => setSubjects([])); }, []);
  useEffect(() => { try { localStorage.setItem("sage-new-session", JSON.stringify(prefs)); } catch { /* ignore */ } }, [prefs]);

  if (!settings) return <Loading message="Getting things ready…" rotate={false} />;
  const opts = settings.options;
  const level = opts.difficulty_levels[String(prefs.difficulty)];
  const needsLanguage = prefs.types.includes("code") || prefs.types.includes("error_analysis");
  const uploading = files.some((f) => f.status === "uploading");
  const readyFiles = files.filter((f) => f.status === "ready" && f.info);
  const canStart = !starting && !uploading && prefs.types.length > 0 && (material.trim().length > 0 || readyFiles.length > 0)
    && prefs.count >= 1 && prefs.count <= opts.max_questions;

  function addFiles(list: FileList | File[]) {
    const accepted = new Set(opts.extensions);
    for (const file of Array.from(list)) {
      const key = `${file.name}-${file.size}-${Math.random()}`;
      const ext = "." + (file.name.split(".").pop() ?? "").toLowerCase();
      if (!accepted.has(ext)) {
        setFiles((f) => [...f, { key, name: file.name, size: file.size, status: "error", error: `Unsupported type. Use ${opts.extensions.join(", ")}.` }]);
        continue;
      }
      if (file.size > opts.max_file_mb * 1024 * 1024) {
        setFiles((f) => [...f, { key, name: file.name, size: file.size, status: "error", error: `Larger than ${opts.max_file_mb} MB.` }]);
        continue;
      }
      setFiles((f) => [...f, { key, name: file.name, size: file.size, status: "uploading" }]);
      api.upload(file)
        .then((info) => setFiles((f) => f.map((x) => (x.key === key ? { ...x, status: "ready", info } : x))))
        .catch((e) => setFiles((f) => f.map((x) => (x.key === key ? { ...x, status: "error", error: asApiError(e).message } : x))));
    }
  }

  function removeFile(f: LocalFile) {
    setFiles((list) => list.filter((x) => x.key !== f.key));
    if (f.info) api.deleteUpload(f.info.id).catch(() => { /* file just stays orphaned in app data */ });
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  }

  function toggleType(id: string) {
    setPrefs((p) => ({ ...p, types: p.types.includes(id) ? p.types.filter((t) => t !== id) : [...p.types, id] }));
  }

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const s = await api.createSession({
        material, subject, upload_ids: readyFiles.map((f) => f.info!.id), types: prefs.types,
        difficulty: prefs.difficulty, adaptive: prefs.adaptive, count: prefs.count, language: prefs.language,
      });
      bumpHistory();
      navigate(`/quiz/${s.id}`);
    } catch (e) {
      setError(asApiError(e).toBody());
      setStarting(false);
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>New study session</h1>
          <p>Tell Sage what to cover, add your notes or slides, and choose how you want to be quizzed.</p>
        </div>
      </div>

      {!settings.key.key_set && (
        <InfoBanner title="Add your API key first">
          Sage Study uses the Claude API. <a href="#/settings">Open Settings</a> to paste your Anthropic API key.
        </InfoBanner>
      )}
      <ErrorBanner error={error} onRetry={start} />

      <section className="card stack">
        <label className="field">
          Subject <span className="field-hint">Optional. Used to track your mastery over time, e.g. "Thermodynamics" or "ECE 210".</span>
          <input className="input" list="subjects" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="e.g. Signals & Systems" maxLength={80} />
          <datalist id="subjects">{subjects.map((s) => <option key={s} value={s} />)}</datalist>
        </label>
        <label className="field">
          What material should be covered?
          <span className="field-hint">A topic, chapter, or learning objectives. Be as specific as you like.</span>
          <textarea className="textarea" rows={4} value={material} onChange={(e) => setMaterial(e.target.value)}
            placeholder={"e.g. Chapter 4: Laplace transforms. Focus on partial fractions, initial/final value theorems, and solving RLC circuits."} />
        </label>

        <div>
          <div className="field" style={{ marginBottom: 6 }}>Documents <span className="field-hint">PDF, Word, PowerPoint, text/Markdown, or photos of notes and slides (PNG/JPG), up to {opts.max_file_mb} MB each.</span></div>
          <div
            className={`dropzone ${drag ? "drag" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") inputRef.current?.click(); }}
          >
            <Upload size={26} />
            <div><strong>Drop files here</strong> or click to browse</div>
            <input ref={inputRef} type="file" multiple hidden accept={opts.extensions.join(",")}
              onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }} />
          </div>
          {files.length > 0 && (
            <div className="file-list">
              {files.map((f) => (
                <div key={f.key} className={`file-item ${f.status === "error" ? "error" : ""}`}>
                  {fileIcon(f.name)}
                  <span className="name" title={f.name}>{f.name}</span>
                  <span className="status">
                    {f.status === "uploading" && <><span className="spinner" /> Uploading…</>}
                    {f.status === "ready" && <><CheckCircle2 size={14} color="var(--correct)" /> {f.info?.kind === "text" && f.info.char_count ? `${f.info.char_count.toLocaleString()} characters extracted` : `Ready · ${formatSize(f.size)}`}</>}
                    {f.status === "error" && f.error}
                  </span>
                  <button className="icon-btn" onClick={() => removeFile(f)} aria-label={`Remove ${f.name}`}><X size={16} /></button>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="card stack">
        <div>
          <div className="card-title">
            <h3>Question types</h3>
            <div className="row">
              <button className="btn sm ghost" onClick={() => setPrefs((p) => ({ ...p, types: opts.question_types.map((t) => t.id) }))}>Select all</button>
              <button className="btn sm ghost" onClick={() => setPrefs((p) => ({ ...p, types: [] }))}>Clear</button>
            </div>
          </div>
          <div className="chips" role="group" aria-label="Question types">
            {opts.question_types.map((t) => (
              <button key={t.id} className={`chip ${prefs.types.includes(t.id) ? "on" : ""}`} onClick={() => toggleType(t.id)} aria-pressed={prefs.types.includes(t.id)}>
                {prefs.types.includes(t.id) && <CheckCircle2 size={14} />} {t.label}
              </button>
            ))}
          </div>
          {prefs.types.length === 0 && <div className="small" style={{ color: "var(--incorrect)", marginTop: 8 }}>Pick at least one type.</div>}
        </div>

        {needsLanguage && (
          <label className="field" style={{ maxWidth: 280 }}>
            Code language
            <select className="select" value={prefs.language} onChange={(e) => setPrefs((p) => ({ ...p, language: e.target.value }))}>
              {opts.code_languages.map((l) => <option key={l}>{l}</option>)}
            </select>
          </label>
        )}

        <div>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h3 style={{ margin: 0 }}>Difficulty</h3>
            <span className="badge primary">{prefs.difficulty} · {level.label}</span>
          </div>
          <input className="slider" type="range" min={1} max={5} step={1} value={prefs.difficulty}
            onChange={(e) => setPrefs((p) => ({ ...p, difficulty: Number(e.target.value) }))} aria-label="Difficulty" />
          <div className="slider-labels">
            {[1, 2, 3, 4, 5].map((d) => <span key={d} className={d === prefs.difficulty ? "on" : ""}>{opts.difficulty_levels[String(d)].label}</span>)}
          </div>
          <div className="muted small" style={{ marginTop: 6 }}>{level.description}</div>
        </div>

        <label className="switch">
          <input type="checkbox" checked={prefs.adaptive} onChange={(e) => setPrefs((p) => ({ ...p, adaptive: e.target.checked }))} />
          <span className="track" />
          <span>
            Adaptive difficulty
            <div className="muted small" style={{ fontWeight: 400 }}>Questions get harder after correct answers and easier after misses, starting from the level above.</div>
          </span>
        </label>

        <div>
          <h3>Number of questions</h3>
          <div className="row">
            <div className="segmented">
              {opts.question_counts.map((n) => (
                <button key={n} className={!customCount && prefs.count === n ? "on" : ""} onClick={() => { setCustomCount(false); setPrefs((p) => ({ ...p, count: n })); }}>{n}</button>
              ))}
              <button className={customCount ? "on" : ""} onClick={() => setCustomCount(true)}>Custom</button>
            </div>
            {customCount && (
              <input className="input" type="number" min={1} max={opts.max_questions} value={prefs.count} style={{ width: 100 }}
                onChange={(e) => setPrefs((p) => ({ ...p, count: Math.max(1, Math.min(opts.max_questions, Number(e.target.value) || 1)) }))}
                aria-label="Custom number of questions" />
            )}
          </div>
        </div>
      </section>

      <div className="row" style={{ marginTop: 22, justifyContent: "flex-end" }}>
        {uploading && <span className="muted small">Waiting for uploads to finish…</span>}
        <button className="btn primary lg" disabled={!canStart} onClick={start}>
          {starting ? <span className="spinner" /> : <Sparkles size={18} />} Start session
        </button>
      </div>
      {!material.trim() && readyFiles.length === 0 && (
        <div className="muted small" style={{ textAlign: "right", marginTop: 8 }}>
          Describe the material or add a document to begin.
        </div>
      )}
    </div>
  );
}
