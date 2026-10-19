import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, ClipboardList, Sparkles, X } from "lucide-react";
import { api, asApiError, type QuizOptionsBody } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, SetSubtopic } from "../lib/types";
import { ErrorBanner } from "./common";
import { LanguagePicker } from "./LanguagePicker";

export type QuizPrefs = QuizOptionsBody;
const PREFS_KEY = "sage-new-session";
const DEFAULT_PREFS: QuizPrefs = { types: ["multiple_choice", "true_false", "short_response"], difficulty: 3, adaptive: false, count: 10, languages: ["Python"] };

export function loadQuizPrefs(): QuizPrefs {
  try {
    const saved = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}");
    // Saved before several languages could be picked: { language: "C++" }
    if (!Array.isArray(saved.languages) && typeof saved.language === "string") saved.languages = [saved.language];
    delete saved.language;
    return { ...DEFAULT_PREFS, ...saved };
  } catch { return DEFAULT_PREFS; }
}

function saveQuizPrefs(p: QuizPrefs) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* ignore */ }
}

export const needsLanguage = (p: QuizPrefs) => p.types.includes("code") || p.types.includes("error_analysis");

/** Question types, code languages, difficulty, adaptive, and number of questions. */
export function QuizOptionsFields({ prefs, setPrefs }: { prefs: QuizPrefs; setPrefs: (f: (p: QuizPrefs) => QuizPrefs) => void }) {
  const { settings } = useApp();
  const [customCount, setCustomCount] = useState(() => !(settings?.options.question_counts ?? [5, 10, 15, 20]).includes(prefs.count));
  if (!settings) return null;
  const opts = settings.options;
  const level = opts.difficulty_levels[String(prefs.difficulty)];
  const toggleType = (id: string) =>
    setPrefs((p) => ({ ...p, types: p.types.includes(id) ? p.types.filter((t) => t !== id) : [...p.types, id] }));

  return (
    <div className="stack">
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

      {needsLanguage(prefs) && (
        <LanguagePicker options={opts.code_languages} value={prefs.languages} onChange={(languages) => setPrefs((p) => ({ ...p, languages }))} />
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
    </div>
  );
}

/** "Start Quiz" from the Material Breakdown: quiz options for the selected subtopics. */
export function StartQuizDialog({ setId, subtopics, onClose }: { setId: string; subtopics: SetSubtopic[]; onClose: () => void }) {
  const navigate = useNavigate();
  const { settings, bumpHistory } = useApp();
  const [prefs, setPrefsState] = useState<QuizPrefs>(loadQuizPrefs);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const setPrefs = (f: (p: QuizPrefs) => QuizPrefs) => setPrefsState((p) => { const n = f(p); saveQuizPrefs(n); return n; });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const max = settings?.options.max_questions ?? 50;
  const canStart = !starting && prefs.types.length > 0 && (!needsLanguage(prefs) || prefs.languages.length > 0)
    && prefs.count >= 1 && prefs.count <= max;

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const s = await api.startSetQuiz(setId, subtopics.map((s) => s.id), {
        ...prefs, languages: prefs.languages.length ? prefs.languages : ["Python"],
      });
      bumpHistory();
      navigate(`/quiz/${s.id}`);
    } catch (e) {
      setError(asApiError(e).toBody());
      setStarting(false);
    }
  }

  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal quiz-modal" role="dialog" aria-modal="true" aria-labelledby="quiz-title">
        <div className="modal-head">
          <div>
            <h2 id="quiz-title" style={{ margin: 0, display: "flex", alignItems: "center", gap: 8 }}><ClipboardList size={20} /> Start a quiz</h2>
            <div className="muted small" style={{ marginTop: 4 }}>
              On {subtopics.length} subtopic{subtopics.length === 1 ? "" : "s"}: {subtopics.map((s) => s.name).join(", ")}
            </div>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <div className="modal-body">
          <ErrorBanner error={error} compact />
          <QuizOptionsFields prefs={prefs} setPrefs={setPrefs} />
        </div>
        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={start} disabled={!canStart}>
            {starting ? <span className="spinner" /> : <Sparkles size={16} />} Start quiz
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
