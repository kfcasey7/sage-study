import { CheckCircle2, CircleDashed, Lightbulb, XCircle } from "lucide-react";
import { Markdown } from "../components/Markdown";
import type { AnswerView } from "../lib/types";

const OBJECTIVE = new Set(["multiple_choice", "select_all", "true_false", "matching", "ordering"]);

export function FeedbackPanel({ a, type }: { a: AnswerView; type: string }) {
  if (!a.verdict) return null;
  const Icon = a.verdict === "correct" ? CheckCircle2 : a.verdict === "partial" ? CircleDashed : XCircle;
  const label = a.skipped ? "Skipped" : a.verdict === "correct" ? "Correct" : a.verdict === "partial" ? "Partially correct" : "Not quite";
  const showAnswers = a.verdict !== "correct" && !OBJECTIVE.has(type);
  return (
    <div className={`feedback ${a.verdict}`} aria-live="polite">
      <div className="verdict">
        <Icon size={22} /> {label}
        <span className="spacer" />
        <span className="badge" style={{ background: "var(--surface)" }}>{Math.round(a.score ?? 0)} / 100</span>
      </div>
      {a.feedback && <Markdown>{a.feedback}</Markdown>}
      {a.misconception && (
        <p className="small" style={{ marginTop: 8 }}><Lightbulb size={14} style={{ verticalAlign: -2 }} /> <strong>Underlying idea to revisit:</strong> {a.misconception}</p>
      )}
      {showAnswers && a.correct_answer && (
        <>
          <h4>Model answer</h4>
          <div className="answer-box"><Markdown>{a.correct_answer}</Markdown></div>
        </>
      )}
      {OBJECTIVE.has(type) && a.verdict !== "correct" && a.correct_answer && type !== "ordering" && type !== "matching" && (
        <>
          <h4>Correct answer</h4>
          <div className="answer-box"><Markdown>{a.correct_answer}</Markdown></div>
        </>
      )}
      {a.explanation && (
        <>
          <h4>Why</h4>
          <Markdown>{a.explanation}</Markdown>
        </>
      )}
      {a.criteria && a.criteria.length > 0 && (
        <>
          <h4>Rubric</h4>
          <table className="criteria">
            <tbody>
              {a.criteria.map((c, i) => (
                <tr key={i}>
                  <td><strong>{c.criterion}</strong>{c.comment && <div className="muted small">{c.comment}</div>}</td>
                  <td className="pts">{c.awarded}/{c.max}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
