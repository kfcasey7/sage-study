import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { MessageSquareWarning, X } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody } from "../lib/types";
import { ErrorBanner } from "./common";

export type ReportResult = { replaced: boolean; excluded: boolean };

/** Report a poorly made question. Unanswered: it's replaced by a new question at the end of the quiz.
 *  Answered: it stays in the review but no longer counts toward the score. */
export function ReportQuestionDialog({ questionId, answered, onClose, onReported }: {
  questionId: string;
  answered: boolean;
  onClose: () => void;
  onReported: (r: ReportResult) => void;
}) {
  const { settings } = useApp();
  const reasons = settings?.options.report_reasons ?? [];
  const [reason, setReason] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiErrorBody | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit() {
    if (!reason) return;
    setSaving(true);
    setError(null);
    try {
      const r = await api.reportQuestion(questionId, reason, note);
      onReported(r);
      onClose();
    } catch (e) {
      setError(asApiError(e).toBody());
      setSaving(false);
    }
  }

  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal report-modal" role="dialog" aria-modal="true" aria-labelledby="report-title">
        <div className="modal-head">
          <div>
            <h2 id="report-title" style={{ margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
              <MessageSquareWarning size={20} /> Report this question
            </h2>
            <div className="muted small" style={{ marginTop: 4 }}>
              {answered
                ? "It stays in your review but won't count toward your score."
                : "It'll be removed, and a new question on the same topic will be added at the end."}
              {" "}Later questions in this session are written with your report in mind.
            </div>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <div className="modal-body stack">
          <ErrorBanner error={error} compact />
          <div className="report-reasons" role="radiogroup" aria-label="What's wrong with it?">
            {reasons.map((r) => (
              <label key={r.id} className={`report-reason ${reason === r.id ? "on" : ""}`}>
                <input type="radio" name="report-reason" value={r.id} checked={reason === r.id} onChange={() => setReason(r.id)} />
                {r.label}
              </label>
            ))}
          </div>
          <label className="field">
            Details (optional)
            <textarea className="textarea" rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Option B is also correct because…" />
          </label>
        </div>
        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={submit} disabled={!reason || saving}>
            {saving && <span className="spinner" />} Report question
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
