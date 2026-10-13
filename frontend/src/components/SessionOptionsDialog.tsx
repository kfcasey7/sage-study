import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, FileImage, FileText, Info, Presentation, X } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, SessionOptions, SessionView, UploadInfo } from "../lib/types";
import { ErrorBanner, formatDateTime } from "./common";

function fileIcon(f: UploadInfo) {
  if (f.kind === "image") return <FileImage size={16} />;
  if (f.source_type === "pptx") return <Presentation size={16} />;
  return <FileText size={16} />;
}

function fileDetail(f: UploadInfo): string {
  if (f.kind === "text" && f.char_count) return `${f.source_type.toUpperCase()} · ${f.char_count.toLocaleString()} characters extracted`;
  if (f.kind === "pdf") return "Scanned PDF · read directly by Claude";
  if (f.kind === "image") return "Image · read directly by Claude";
  return f.source_type.toUpperCase();
}

/** Everything chosen when the session was created. Question options can be changed while the
 *  session is in progress; changes apply to questions not yet answered or on screen. */
export function SessionOptionsDialog({ sessionId, onClose, onSaved }: {
  sessionId: string;
  onClose: () => void;
  onSaved?: (view: SessionView) => void;
}) {
  const { settings, toast } = useApp();
  const [session, setSession] = useState<SessionView | null>(null);
  const [opts, setOpts] = useState<SessionOptions | null>(null);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.session(sessionId)
      .then((s) => {
        setSession(s);
        const c = s.config;
        setOpts({ types: c.types, difficulty: c.difficulty, adaptive: c.adaptive, count: c.count, language: c.language, feedback_mode: c.feedback_mode });
      })
      .catch((e) => setError(asApiError(e).toBody()));
  }, [sessionId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const o = settings?.options;
  const editable = !!session?.editable;
  const minCount = session ? Math.max(1, session.progress.served) : 1;  // answered + the one on screen
  const original = session?.config;
  const dirty = !!(opts && original && (
    opts.types.join() !== original.types.join() || opts.difficulty !== original.difficulty || opts.adaptive !== original.adaptive
    || opts.count !== original.count || opts.language !== original.language || opts.feedback_mode !== original.feedback_mode));

  async function save() {
    if (!opts) return;
    setSaving(true);
    setError(null);
    try {
      const view = await api.updateOptions(sessionId, opts);
      setSession(view);
      onSaved?.(view);
      toast("Options saved. Upcoming questions will use them.", "success");
      onClose();
    } catch (e) {
      setError(asApiError(e).toBody());
    } finally {
      setSaving(false);
    }
  }

  function toggleType(id: string) {
    setOpts((p) => p && ({ ...p, types: p.types.includes(id) ? p.types.filter((t) => t !== id) : [...p.types, id] }));
  }

  const needsLanguage = !!opts && (opts.types.includes("code") || opts.types.includes("error_analysis"));
  const modelLabel = (id?: string) => o?.models.find((m) => m.id === id)?.label ?? id ?? "–";

  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="session-options-title">
        <div className="modal-head">
          <div>
            <h2 id="session-options-title" style={{ margin: 0 }}>{session?.title || "Study session"}</h2>
            {session && (
              <div className="muted small" style={{ marginTop: 4 }}>
                Created {formatDateTime(session.created_at)} · {session.progress.answered} of {session.config.count} answered
                {session.progress.skipped_waiting > 0 && ` · ${session.progress.skipped_waiting} skipped for later`}
                {!editable && " · finished"}
              </div>
            )}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>

        <div className="modal-body">
          <ErrorBanner error={error} compact />
          {!session || !opts || !o ? (
            !error && <div className="skeleton" style={{ height: 240 }} />
          ) : (
            <div className="stack">
              <section>
                <h3>Material</h3>
                <dl className="kv">
                  <dt>Subject</dt><dd>{session.subject || <span className="muted">None</span>}</dd>
                  <dt>What to cover</dt>
                  <dd>{session.material ? <div className="prompt-box">{session.material}</div> : <span className="muted">No description (documents only)</span>}</dd>
                  <dt>Files</dt>
                  <dd>
                    {session.documents.length === 0 ? <span className="muted">No files uploaded</span> : (
                      <div className="file-list" style={{ marginTop: 0 }}>
                        {session.documents.map((f) => (
                          <div key={f.id} className="file-item">
                            {fileIcon(f)}<span className="name" title={f.filename}>{f.filename}</span><span className="status">{fileDetail(f)}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {session.config.docs_truncated && <div className="small" style={{ color: "var(--partial-text)", marginTop: 6 }}>Long documents: each request uses the most relevant excerpts.</div>}
                  </dd>
                  {session.subtopics.length > 0 && (<>
                    <dt>Subtopics</dt>
                    <dd><div className="chips">{session.subtopics.map((s) => <span key={s.id} className="badge primary" title={s.description}>{s.name}</span>)}</div></dd>
                  </>)}
                </dl>
              </section>

              <section>
                <h3>Question options</h3>
                {editable ? (
                  <div className="banner info" style={{ marginBottom: 12 }}>
                    <Info size={18} />
                    <div className="banner-body small">
                      Changes apply to questions you haven't answered yet. Answered questions and the one on screen stay the same.
                      Skipped questions that no longer fit are rewritten when they come back around.
                    </div>
                  </div>
                ) : <p className="muted small">This session is finished, so its options are shown for reference.</p>}

                <fieldset disabled={!editable} className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
                  <div>
                    <div className="field" style={{ marginBottom: 6 }}>Question types</div>
                    <div className="chips">
                      {o.question_types.map((t) => (
                        <button key={t.id} type="button" className={`chip ${opts.types.includes(t.id) ? "on" : ""}`} onClick={() => toggleType(t.id)} aria-pressed={opts.types.includes(t.id)}>
                          {opts.types.includes(t.id) && <CheckCircle2 size={14} />} {t.label}
                        </button>
                      ))}
                    </div>
                    {opts.types.length === 0 && <div className="small" style={{ color: "var(--incorrect)", marginTop: 6 }}>Pick at least one type.</div>}
                  </div>

                  {needsLanguage && (
                    <label className="field" style={{ maxWidth: 260 }}>
                      Code language
                      <select className="select" value={opts.language} onChange={(e) => setOpts({ ...opts, language: e.target.value })}>
                        {o.code_languages.map((l) => <option key={l}>{l}</option>)}
                      </select>
                    </label>
                  )}

                  <div>
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <span className="field">Difficulty</span>
                      <span className="badge primary">{opts.difficulty} · {o.difficulty_levels[String(opts.difficulty)].label}</span>
                    </div>
                    <input className="slider" type="range" min={1} max={5} value={opts.difficulty} aria-label="Difficulty"
                      onChange={(e) => setOpts({ ...opts, difficulty: Number(e.target.value) })} />
                    <div className="muted small">{o.difficulty_levels[String(opts.difficulty)].description}{opts.adaptive ? " (adaptive: the starting level from here on)" : ""}</div>
                  </div>

                  <label className="switch">
                    <input type="checkbox" checked={opts.adaptive} onChange={(e) => setOpts({ ...opts, adaptive: e.target.checked })} />
                    <span className="track" />
                    <span>Adaptive difficulty</span>
                  </label>

                  <div className="grid-2">
                    <label className="field">
                      Total questions
                      <input className="input" type="number" min={minCount} max={o.max_questions} value={opts.count}
                        onChange={(e) => setOpts({ ...opts, count: Math.max(1, Math.min(o.max_questions, Number(e.target.value) || 1)) })} />
                      <span className="field-hint">At least {minCount} (already answered{session.progress.served > session.progress.answered ? " or on screen" : ""}).</span>
                    </label>
                    <div className="field">
                      Show feedback
                      <div className="segmented" style={{ width: "fit-content" }}>
                        <button type="button" className={opts.feedback_mode === "immediate" ? "on" : ""} onClick={() => setOpts({ ...opts, feedback_mode: "immediate" })}>After each answer</button>
                        <button type="button" className={opts.feedback_mode === "end" ? "on" : ""} onClick={() => setOpts({ ...opts, feedback_mode: "end" })}>At the end</button>
                      </div>
                    </div>
                  </div>
                </fieldset>
              </section>

              <section>
                <h3>Models</h3>
                <dl className="kv">
                  <dt>Questions</dt><dd>{modelLabel(session.config.model_fast)}</dd>
                  <dt>Grading &amp; study guide</dt><dd>{modelLabel(session.config.model_smart)}</dd>
                </dl>
              </section>
            </div>
          )}
        </div>

        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose}>{editable ? "Cancel" : "Close"}</button>
          {editable && (
            <button className="btn primary" onClick={save}
              disabled={!dirty || saving || !opts || opts.types.length === 0 || opts.count < minCount}>
              {saving && <span className="spinner" />} Save changes
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
