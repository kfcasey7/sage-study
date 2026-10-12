/** Inputs for objectively graded question types (graded locally on the backend). */
import { Fragment } from "react";
import { Check, X } from "lucide-react";
import { Markdown } from "../components/Markdown";
import { MarkdownInline } from "../components/MarkdownInline";
import type { AnswerKey, QuestionView } from "../lib/types";

export interface InputProps {
  q: QuestionView;
  value: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
  locked: boolean;
  answerKey?: AnswerKey;
}

const LETTERS = "ABCDEFGH";

export function MultipleChoice({ q, value, onChange, locked, answerKey }: InputProps) {
  const choice = value.choice as number | undefined;
  return (
    <div role="radiogroup" aria-label="Options">
      {q.options!.map((o, i) => {
        const isCorrect = answerKey?.correct_ids?.includes(o.id);
        const state = locked && answerKey ? (isCorrect ? "correct" : choice === o.id ? "incorrect" : "") : choice === o.id ? "selected" : "";
        return (
          <label key={o.id} className={`option ${state} ${locked ? "locked" : ""}`}>
            <input type="radio" name={`mc-${q.id}`} checked={choice === o.id} disabled={locked} onChange={() => onChange({ choice: o.id })} />
            <span className="opt-key">{LETTERS[i]}</span>
            <span className="opt-text"><Markdown>{o.text}</Markdown></span>
            {locked && answerKey && isCorrect && <Check size={18} color="var(--correct)" />}
            {locked && answerKey && !isCorrect && choice === o.id && <X size={18} color="var(--incorrect)" />}
          </label>
        );
      })}
    </div>
  );
}

export function SelectAll({ q, value, onChange, locked, answerKey }: InputProps) {
  const chosen = new Set((value.choices as number[] | undefined) ?? []);
  function toggle(id: number) {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id); else next.add(id);
    onChange({ choices: [...next].sort((a, b) => a - b) });
  }
  return (
    <div>
      <div className="muted small" style={{ marginBottom: 8 }}>Select all that apply.</div>
      {q.options!.map((o, i) => {
        const isCorrect = answerKey?.correct_ids?.includes(o.id);
        const picked = chosen.has(o.id);
        const state = locked && answerKey ? (isCorrect ? "correct" : picked ? "incorrect" : "") : picked ? "selected" : "";
        return (
          <label key={o.id} className={`option ${state} ${locked ? "locked" : ""}`}>
            <input type="checkbox" checked={picked} disabled={locked} onChange={() => toggle(o.id)} />
            <span className="opt-key">{LETTERS[i]}</span>
            <span className="opt-text"><Markdown>{o.text}</Markdown></span>
            {locked && answerKey && isCorrect && !picked && <span className="badge correct">Missed</span>}
          </label>
        );
      })}
    </div>
  );
}

export function TrueFalse({ value, onChange, locked, answerKey }: InputProps) {
  const v = value.value as boolean | undefined;
  return (
    <div className="tf-buttons" role="radiogroup">
      {[true, false].map((b) => {
        const state = locked && answerKey ? (answerKey.correct === b ? "correct" : v === b ? "incorrect" : "") : v === b ? "selected" : "";
        return (
          <button key={String(b)} type="button" role="radio" aria-checked={v === b} className={`option ${state} ${locked ? "locked" : ""}`}
            disabled={locked} onClick={() => onChange({ value: b })}>
            {b ? "True" : "False"}
          </button>
        );
      })}
    </div>
  );
}

const BLANK = /\{\{\s*blank\s*\}\}/;

export function FillBlank({ q, value, onChange, locked, answerKey }: InputProps) {
  const n = q.blank_count ?? 1;
  const blanks = (value.blanks as string[] | undefined) ?? Array(n).fill("");
  const parts = q.prompt.split(BLANK);
  function set(i: number, text: string) {
    const next = [...blanks];
    next[i] = text;
    onChange({ blanks: next });
  }
  return (
    <div className="blank-sentence">
      {parts.map((part, i) => (
        <Fragment key={i}>
          <MarkdownInline>{part}</MarkdownInline>
          {i < parts.length - 1 && (
            <>
              <input
                className={`blank-input ${locked && answerKey?.blanks ? (blanks[i]?.trim().toLowerCase() === answerKey.blanks[i]?.toLowerCase() ? "correct" : "") : ""}`}
                value={blanks[i] ?? ""}
                disabled={locked}
                onChange={(e) => set(i, e.target.value)}
                aria-label={`Blank ${i + 1}`}
                autoFocus={i === 0}
              />
              {locked && answerKey?.blanks && blanks[i]?.trim().toLowerCase() !== answerKey.blanks[i]?.toLowerCase() && (
                <span className="badge correct" style={{ marginRight: 6 }}>{answerKey.blanks[i]}</span>
              )}
            </>
          )}
        </Fragment>
      ))}
    </div>
  );
}

export function Matching({ q, value, onChange, locked, answerKey }: InputProps) {
  const left = q.left!;
  const right = q.right!;
  const matches = (value.matches as (number | null)[] | undefined) ?? Array(left.length).fill(null);
  function set(i: number, v: string) {
    const next = [...matches];
    next[i] = v === "" ? null : Number(v);
    onChange({ matches: next });
  }
  return (
    <div>
      {left.map((l, i) => {
        const correctIdx = answerKey?.matches?.[i];
        const state = locked && answerKey ? (matches[i] === correctIdx ? "correct" : "incorrect") : "";
        return (
          <div key={i} className={`match-row ${state}`}>
            <div><MarkdownInline>{l}</MarkdownInline></div>
            <span className="arrow">→</span>
            <div>
              <select className="select" value={matches[i] ?? ""} disabled={locked} onChange={(e) => set(i, e.target.value)} aria-label={`Match for ${l}`}>
                <option value="">Choose…</option>
                {right.map((r, j) => <option key={j} value={j}>{r}</option>)}
              </select>
              {state === "incorrect" && correctIdx != null && <div className="small" style={{ color: "var(--correct)", marginTop: 4 }}>Correct: {right[correctIdx]}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
